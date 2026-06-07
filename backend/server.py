"""
FloorPlan3D — Flask API Server  v6
====================================
v6 Additions:
- /bom endpoint: Bill of Materials (CSV/JSON)
- /compliance endpoint: Automated building code checks
- /export/stl endpoint: 3D-print-ready STL geometry
- /command endpoint: Natural language command parsing
- Enhanced _sanitize for numpy edge cases
"""

import os
import io
import time
import json
import base64
import math
import struct
import logging
import numpy as np
import cv2
from flask import Flask, request, jsonify, send_from_directory, Response, make_response
from flask_cors import CORS
from detector import detect_floor_plan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("floorplan3d")

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app, resources={r"/*": {"origins": "*"}})

MAX_BYTES = 20 * 1024 * 1024

_model_cache = {}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _read_image_bytes() -> bytes:
    ct = (request.content_type or "").lower()
    if "multipart/form-data" in ct:
        f = request.files.get("image")
        if not f:
            raise ValueError("Multipart request missing 'image' file field")
        return f.read()
    if "application/json" in ct:
        data = request.get_json(silent=True) or {}
        b64  = data.get("image", "")
        if not b64:
            raise ValueError("JSON body missing 'image' field")
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        try:
            return base64.b64decode(b64)
        except Exception:
            raise ValueError("Invalid base64 in 'image' field")
    raw = request.data
    if raw:
        return raw
    raise ValueError("Could not extract image — unsupported content type")


def _sanitize(obj):
    """Recursively convert numpy types to native Python for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    return obj


def _timed_response(data: dict, t0: float) -> Response:
    resp = jsonify(_sanitize(data))
    resp.headers["X-Process-Time-Ms"] = str(round((time.perf_counter()-t0)*1000, 1))
    resp.headers["X-Server"] = "FloorPlan3D v6"
    return resp


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("../frontend", "index.html")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "server": "Floor Plan Rule-Based Engine",
        "numpy":  np.__version__,
        "max_image_mb": MAX_BYTES // (1024*1024),
    })


@app.route("/status")
def status():
    import sys, platform
    return jsonify({
        "status":   "ok",
        "server":   "Floor Plan",
        "numpy":    np.__version__,
        "python":   sys.version,
        "platform": platform.platform(),
        "pid":      os.getpid(),
    })


@app.route("/analyze", methods=["POST"])
def analyze():
    t0 = time.perf_counter()
    try:
        image_bytes = _read_image_bytes()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if len(image_bytes) > MAX_BYTES:
        return jsonify({"error": f"Image too large (max {MAX_BYTES//(1024*1024)} MB)"}), 413

    if image_bytes.startswith(b"%PDF-"):
        try:
            import fitz
            doc = fitz.open(stream=image_bytes, filetype="pdf")
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=300) # High-res rendering to preserve vector intent
            probe = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if probe.shape[2] in [3, 4]:
                probe = cv2.cvtColor(probe, cv2.COLOR_RGBA2GRAY if probe.shape[2]==4 else cv2.COLOR_RGB2GRAY)
        except ImportError:
            return jsonify({"error": "PyMuPDF is not installed on the server to parse PDFs."}), 501
        except Exception as e:
            return jsonify({"error": f"Failed to parse PDF: {str(e)}"}), 422
    else:
        arr   = np.frombuffer(image_bytes, np.uint8)
        probe = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)

    if probe is None:
        return jsonify({"error": "Uploaded data is not a recognizable image or PDF"}), 422

    h, w = probe.shape[:2]
    size_kb = len(image_bytes)//1024
    logger.info(f"Analyzing {w}×{h} image ({size_kb} KB)")

    try:
        result = detect_floor_plan(image_bytes)
        logger.info(f"Done in {round((time.perf_counter()-t0)*1000)} ms — {result['summary']}")
        return _timed_response(result, t0)
    except ValueError as e:
        logger.warning(f"Detection value error: {e}")
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        logger.exception("Unexpected detection error")
        return jsonify({"error": f"Internal error: {str(e)}"}), 500


@app.route("/demo")
def demo():
    preset = request.args.get("preset", "complex")
    t0     = time.perf_counter()
    logger.info(f"Generating demo plan (preset={preset})")

    img = _generate_demo_plan(preset)
    _, buf = cv2.imencode(".png", img)
    image_bytes = buf.tobytes()

    result = detect_floor_plan(image_bytes)
    result["source_image"] = base64.b64encode(image_bytes).decode()
    result["preset"] = preset
    return _timed_response(result, t0)


@app.route("/rooms", methods=["POST"])
def rooms_only():
    t0 = time.perf_counter()
    try:
        image_bytes = _read_image_bytes()
        result      = detect_floor_plan(image_bytes)
        return _timed_response({"rooms": result["rooms"],
                                 "fixtures": result.get("fixtures", []),
                                 "summary": result["summary"]}, t0)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# BOM (Bill of Materials)
# ─────────────────────────────────────────────────────────────

@app.route("/bom", methods=["POST"])
def bom():
    """Generate Bill of Materials from detection data."""
    t0 = time.perf_counter()
    data = request.get_json(silent=True) or {}
    scale = data.get("scale", 1.0)  # px-to-meter
    world = data.get("world_size", 20.0)
    iw = data.get("image_width", 800)
    ih = data.get("image_height", 600)

    def seg_len(s):
        dx = s["x2"]-s["x1"]
        dy = s["y2"]-s["y1"]
        return math.sqrt(dx*dx+dy*dy) * (world/iw)

    def seg_thick(s, default=0.15):
        return max(0.08, (s.get("thickness_px", default*iw/world)) * (world/iw) * 2)

    # Walls
    outer_walls = data.get("outer_walls", [])
    inner_walls = data.get("inner_walls", [])
    closets = data.get("closets", [])

    total_outer_len = sum(seg_len(s) for s in outer_walls)
    total_inner_len = sum(seg_len(s) for s in inner_walls)
    total_closet_len = sum(seg_len(s) for s in closets)
    wall_height = data.get("wall_height", 2.8)

    outer_area = total_outer_len * wall_height
    inner_area = total_inner_len * wall_height
    closet_area = total_closet_len * wall_height

    # Quantities
    drywall_sheets = math.ceil((outer_area + inner_area) * 2 / 4.88)  # 4x8 ft sheets
    paint_liters = round((outer_area + inner_area) * 2 * 0.1, 1)  # ~0.1 L/m²
    insulation_m2 = round(outer_area, 1)

    # Floor area
    rooms = data.get("rooms", [])
    total_floor = sum(r.get("area_px", 0) * (world/iw) * (world/ih) for r in rooms)
    flooring_m2 = round(total_floor, 1)

    n_doors = len(data.get("doors", []))
    n_windows = len(data.get("windows", []))
    n_fixtures = len(data.get("fixtures", []))

    bom_items = [
        {"category": "Structure", "item": "Outer Wall Length", "quantity": round(total_outer_len, 1), "unit": "m"},
        {"category": "Structure", "item": "Inner Wall Length", "quantity": round(total_inner_len, 1), "unit": "m"},
        {"category": "Structure", "item": "Closet Wall Length", "quantity": round(total_closet_len, 1), "unit": "m"},
        {"category": "Structure", "item": "Wall Height", "quantity": wall_height, "unit": "m"},
        {"category": "Surfaces", "item": "Outer Wall Area", "quantity": round(outer_area, 1), "unit": "m²"},
        {"category": "Surfaces", "item": "Inner Wall Area", "quantity": round(inner_area, 1), "unit": "m²"},
        {"category": "Surfaces", "item": "Total Floor Area", "quantity": flooring_m2, "unit": "m²"},
        {"category": "Materials", "item": "Drywall Sheets (4×8ft)", "quantity": drywall_sheets, "unit": "pcs"},
        {"category": "Materials", "item": "Paint (2 coats)", "quantity": paint_liters, "unit": "L"},
        {"category": "Materials", "item": "Insulation (exterior)", "quantity": insulation_m2, "unit": "m²"},
        {"category": "Materials", "item": "Flooring", "quantity": flooring_m2, "unit": "m²"},
        {"category": "Elements", "item": "Doors", "quantity": n_doors, "unit": "pcs"},
        {"category": "Elements", "item": "Windows", "quantity": n_windows, "unit": "pcs"},
        {"category": "Elements", "item": "Fixtures", "quantity": n_fixtures, "unit": "pcs"},
        {"category": "Rooms", "item": "Total Rooms", "quantity": len(rooms), "unit": ""},
    ]

    # Per-room breakdown
    for r in rooms:
        area = round(r.get("area_px", 0) * (world/iw) * (world/ih), 1)
        bom_items.append({"category": "Room Detail", "item": r.get("label", "Room"), "quantity": area, "unit": "m²"})

    return _timed_response({"bom": bom_items, "totals": {
        "wall_length_m": round(total_outer_len + total_inner_len + total_closet_len, 1),
        "wall_area_m2": round(outer_area + inner_area + closet_area, 1),
        "floor_area_m2": flooring_m2,
        "doors": n_doors, "windows": n_windows,
    }}, t0)


# ─────────────────────────────────────────────────────────────
# Code Compliance Checks
# ─────────────────────────────────────────────────────────────

@app.route("/compliance", methods=["POST"])
def compliance():
    """Run preliminary building code compliance checks."""
    t0 = time.perf_counter()
    data = request.get_json(silent=True) or {}
    world = data.get("world_size", 20.0)
    iw = data.get("image_width", 800)
    ih = data.get("image_height", 600)
    wall_height = data.get("wall_height", 2.8)

    issues = []
    warnings = []
    passed = []

    # Door width check (IRC code: min 32" = 0.81m for egress)
    for i, door in enumerate(data.get("doors", [])):
        dw = door.get("radius_px", 30) * (world/iw) * 2
        if dw < 0.81:
            issues.append({"severity": "error", "code": "IRC R311.2",
                          "message": f"Door {i+1}: width {dw:.2f}m < 0.81m minimum",
                          "element": "door", "index": i})
        elif dw < 0.91:
            warnings.append({"severity": "warning", "code": "ADA 404.2.3",
                            "message": f"Door {i+1}: width {dw:.2f}m < 0.91m (ADA accessible minimum)",
                            "element": "door", "index": i})
        else:
            passed.append({"code": "IRC R311.2", "message": f"Door {i+1}: width OK ({dw:.2f}m)", "element": "door"})

    # Room checks
    for i, room in enumerate(data.get("rooms", [])):
        area = room.get("area_px", 0) * (world/iw) * (world/ih)
        rtype = room.get("room_type", "unknown")

        # Bedroom minimum area (IRC R304: 70 sq ft = 6.5 m²)
        if rtype == "bedroom" and area < 6.5:
            issues.append({"severity": "error", "code": "IRC R304.1",
                          "message": f"{room.get('label','Room')}: area {area:.1f}m² < 6.5m² (bedroom min)",
                          "element": "room", "index": i})
        elif rtype == "bedroom":
            passed.append({"code": "IRC R304.1", "message": f"{room.get('label','Room')}: bedroom area OK ({area:.1f}m²)"})

        # Minimum habitable room (IRC: 70 sq ft = 6.5 m²)
        if rtype not in ("closet", "hallway", "bathroom") and area < 6.5:
            warnings.append({"severity": "warning", "code": "IRC R304.2",
                            "message": f"{room.get('label','Room')}: area {area:.1f}m² < 6.5m² habitable min",
                            "element": "room", "index": i})

    # Stair checks
    for i, stair in enumerate(data.get("stairs", [])):
        steps = stair.get("steps", 6)
        step_rise = data.get("step_rise", 0.18)
        if step_rise > 0.196:
            issues.append({"severity": "error", "code": "IRC R311.7.5.1",
                          "message": f"Stair {i+1}: riser height {step_rise:.3f}m > 0.196m max",
                          "element": "stair", "index": i})
        elif step_rise < 0.10:
            warnings.append({"severity": "warning", "code": "IRC R311.7.5.1",
                            "message": f"Stair {i+1}: riser height {step_rise:.3f}m unusually low",
                            "element": "stair", "index": i})
        else:
            passed.append({"code": "IRC R311.7.5.1", "message": f"Stair {i+1}: riser OK ({step_rise:.3f}m)"})

    # Wall height check
    if wall_height < 2.13:
        issues.append({"severity": "error", "code": "IRC R305.1",
                      "message": f"Ceiling height {wall_height:.2f}m < 2.13m (7ft) minimum"})
    elif wall_height < 2.44:
        warnings.append({"severity": "warning", "code": "IRC R305.1",
                        "message": f"Ceiling height {wall_height:.2f}m — acceptable but low"})
    else:
        passed.append({"code": "IRC R305.1", "message": f"Ceiling height OK ({wall_height:.2f}m)"})

    return _timed_response({
        "issues": issues, "warnings": warnings, "passed": passed,
        "summary": {
            "errors": len(issues), "warnings": len(warnings), "passed": len(passed),
            "score": max(0, 100 - len(issues)*15 - len(warnings)*5)
        }
    }, t0)


# ─────────────────────────────────────────────────────────────
# Command Parser (Natural Language → Structured Action)
# ─────────────────────────────────────────────────────────────

@app.route("/command", methods=["POST"])
def parse_command():
    """Parse a natural language command into a structured action."""
    t0 = time.perf_counter()
    data = request.get_json(silent=True) or {}
    text = (data.get("text", "") or "").strip().lower()
    context = data.get("context", {})

    if not text:
        return jsonify({"error": "No command text provided"}), 400

    action = _parse_nl_command(text, context)
    return _timed_response({"action": action, "original": text}, t0)


def _parse_nl_command(text, context=None):
    """Rule-based NL command parser. Returns structured action dict."""
    # Navigation commands
    nav_map = {
        "kitchen": "kitchen", "living": "living", "bedroom": "bedroom",
        "bathroom": "bathroom", "bath": "bathroom", "hallway": "hallway",
        "closet": "closet", "entrance": "entrance", "dining": "dining",
        "garage": "garage", "laundry": "laundry", "office": "office",
    }
    for keyword, room in nav_map.items():
        if f"show me the {keyword}" in text or f"go to {keyword}" in text or f"navigate to {keyword}" in text or f"focus on {keyword}" in text:
            return {"type": "navigate", "target": room}

    # Visibility commands
    if "hide" in text:
        for el in ["walls", "doors", "windows", "stairs", "closets", "fixtures", "rooms", "floor", "labels"]:
            if el in text:
                return {"type": "visibility", "element": el, "visible": False}
    if "show" in text and "all" in text:
        return {"type": "visibility", "element": "all", "visible": True}
    if "show" in text:
        for el in ["walls", "doors", "windows", "stairs", "closets", "fixtures", "rooms", "floor", "labels"]:
            if el in text:
                return {"type": "visibility", "element": el, "visible": True}

    # Theme commands
    for theme in ["modern", "classic", "industrial"]:
        if theme in text and ("theme" in text or "style" in text or "material" in text or "switch" in text or "change" in text):
            return {"type": "theme", "name": theme}

    # Lighting commands
    for preset in ["morning", "noon", "evening", "night"]:
        if preset in text and ("light" in text or "time" in text or "set" in text or "switch" in text or "change" in text):
            return {"type": "lighting", "preset": preset}

    # Camera commands
    cam_map = {"top": "top", "bird": "top", "above": "top",
               "front": "front", "side": "front",
               "perspective": "persp", "3d": "persp",
               "isometric": "iso", "iso": "iso",
               "walk": "walkthrough", "first person": "walkthrough",
               "corner": "corner"}
    for keyword, view in cam_map.items():
        if keyword in text and ("view" in text or "camera" in text or "switch" in text or "show" in text):
            return {"type": "camera", "view": view}

    # Measurement
    if "measure" in text:
        return {"type": "tool", "name": "measure"}
    if "select" in text:
        return {"type": "tool", "name": "select"}

    # Edit commands
    if "add" in text and "wall" in text:
        return {"type": "tool", "name": "addwall"}
    if "delete" in text or "remove" in text:
        if "selected" in text or "this" in text:
            return {"type": "action", "name": "delete_selected"}

    # Undo/redo
    if "undo" in text:
        return {"type": "action", "name": "undo"}
    if "redo" in text:
        return {"type": "action", "name": "redo"}

    # Export
    if "export" in text or "download" in text:
        for fmt in ["svg", "dxf", "obj", "stl", "gltf", "screenshot", "png"]:
            if fmt in text:
                return {"type": "export", "format": fmt}

    # Clipping
    if "clip" in text or "section" in text or "cut" in text:
        if "off" in text or "disable" in text:
            return {"type": "clipping", "enabled": False}
        return {"type": "clipping", "enabled": True}

    # Wireframe
    if "wireframe" in text:
        return {"type": "wireframe", "enabled": "off" not in text}

    # Screenshot
    if "screenshot" in text or "capture" in text:
        return {"type": "export", "format": "screenshot"}

    # Fullscreen
    if "fullscreen" in text or "full screen" in text:
        return {"type": "action", "name": "fullscreen"}

    # BOM
    if "bom" in text or "bill of materials" in text or "quantities" in text:
        return {"type": "action", "name": "show_bom"}

    # Compliance
    if "compliance" in text or "code check" in text or "building code" in text:
        return {"type": "action", "name": "show_compliance"}

    return {"type": "unknown", "message": f"Could not parse: '{text}'"}


# ─────────────────────────────────────────────────────────────
# Export: SVG
# ─────────────────────────────────────────────────────────────

@app.route("/export/svg", methods=["POST"])
def export_svg():
    t0 = time.perf_counter()
    try:
        data = request.get_json(silent=True) or {}
        if not data.get("outer_walls"):
            return jsonify({"error": "No model data provided"}), 400
        svg = _generate_svg(data)
        resp = make_response(svg)
        resp.headers["Content-Type"] = "image/svg+xml"
        resp.headers["Content-Disposition"] = "attachment; filename=floorplan.svg"
        return resp
    except Exception as e:
        logger.exception("SVG export error")
        return jsonify({"error": str(e)}), 500


@app.route("/export/dxf", methods=["POST"])
def export_dxf():
    t0 = time.perf_counter()
    try:
        data = request.get_json(silent=True) or {}
        if not data.get("outer_walls"):
            return jsonify({"error": "No model data provided"}), 400
        dxf = _generate_dxf(data)
        resp = make_response(dxf)
        resp.headers["Content-Type"] = "application/dxf"
        resp.headers["Content-Disposition"] = "attachment; filename=floorplan.dxf"
        return resp
    except Exception as e:
        logger.exception("DXF export error")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Export: STL (3D Print Ready)
# ─────────────────────────────────────────────────────────────

@app.route("/export/stl", methods=["POST"])
def export_stl():
    """Generate binary STL for 3D printing."""
    t0 = time.perf_counter()
    try:
        data = request.get_json(silent=True) or {}
        if not data.get("outer_walls"):
            return jsonify({"error": "No model data provided"}), 400

        stl_bytes = _generate_stl(data)
        resp = make_response(stl_bytes)
        resp.headers["Content-Type"] = "application/octet-stream"
        resp.headers["Content-Disposition"] = "attachment; filename=floorplan.stl"
        return resp
    except Exception as e:
        logger.exception("STL export error")
        return jsonify({"error": str(e)}), 500


def _generate_stl(data):
    """Generate binary STL from wall segments."""
    world = data.get("world_size", 20.0)
    iw = data.get("image_width", 800)
    ih = data.get("image_height", 600)
    wall_h = data.get("wall_height", 2.8)
    scale = 100  # mm scale for 3D printing (1m = 100mm at 1:10)

    def px(x): return (x * (world/iw) - world/2) * scale
    def pz(y): return (y * (world/ih) - world/2) * scale

    triangles = []

    def add_box(x1, z1, x2, z2, h, tk):
        dx, dz = x2-x1, z2-z1
        ln = math.sqrt(dx*dx+dz*dz)
        if ln < 0.01: return
        nx, nz = -dz/ln * tk/2, dx/ln * tk/2

        # 8 corners
        c = [
            (x1+nx, 0,    z1+nz), (x2+nx, 0,    z2+nz),
            (x2+nx, h,    z2+nz), (x1+nx, h,    z1+nz),
            (x1-nx, 0,    z1-nz), (x2-nx, 0,    z2-nz),
            (x2-nx, h,    z2-nz), (x1-nx, h,    z1-nz),
        ]
        # 6 faces, 2 triangles each
        faces = [
            (0,1,2,3), (4,5,6,7), (0,1,5,4),
            (2,3,7,6), (0,3,7,4), (1,2,6,5),
        ]
        for f in faces:
            v0,v1,v2,v3 = [c[i] for i in f]
            triangles.append((v0,v1,v2))
            triangles.append((v0,v2,v3))

    for seg in data.get("outer_walls", []):
        tk = max(0.08, (seg.get("thickness_px", 12)) * (world/iw) * 2) * scale
        add_box(px(seg["x1"]), pz(seg["y1"]), px(seg["x2"]), pz(seg["y2"]), wall_h*scale, tk)

    for seg in data.get("inner_walls", []):
        tk = max(0.06, (seg.get("thickness_px", 8)) * (world/iw) * 2) * scale
        add_box(px(seg["x1"]), pz(seg["y1"]), px(seg["x2"]), pz(seg["y2"]), wall_h*scale, tk)

    for seg in data.get("closets", []):
        tk = max(0.04, (seg.get("thickness_px", 5)) * (world/iw) * 2) * scale
        add_box(px(seg["x1"]), pz(seg["y1"]), px(seg["x2"]), pz(seg["y2"]), wall_h*0.94*scale, tk)

    # Floor slab
    hw = world/2 * scale
    floor_tris = [
        ((-hw, 0, -hw), (hw, 0, -hw), (hw, 0, hw)),
        ((-hw, 0, -hw), (hw, 0, hw), (-hw, 0, hw)),
    ]
    triangles.extend(floor_tris)

    # Binary STL format
    header = b'\0' * 80
    n_tris = len(triangles)
    buf = io.BytesIO()
    buf.write(header)
    buf.write(struct.pack('<I', n_tris))
    for v0, v1, v2 in triangles:
        # Normal (simplified cross product)
        e1 = (v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2])
        e2 = (v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2])
        n = (e1[1]*e2[2]-e1[2]*e2[1], e1[2]*e2[0]-e1[0]*e2[2], e1[0]*e2[1]-e1[1]*e2[0])
        buf.write(struct.pack('<fff', *n))
        for v in (v0, v1, v2):
            buf.write(struct.pack('<fff', *v))
        buf.write(struct.pack('<H', 0))

    return buf.getvalue()


@app.route("/save", methods=["POST"])
def save_model():
    try:
        data = request.get_json(silent=True) or {}
        model_id = data.get("id", "default")
        _model_cache[model_id] = {
            "data": data.get("model", {}),
            "params": data.get("params", {}),
            "timestamp": time.time(),
        }
        logger.info(f"Model saved: {model_id}")
        return jsonify({"status": "saved", "id": model_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/load/<model_id>")
def load_model(model_id):
    if model_id in _model_cache:
        return jsonify({"status": "ok", **_model_cache[model_id]})
    return jsonify({"error": "Model not found"}), 404


# ─────────────────────────────────────────────────────────────
# SVG Generator
# ─────────────────────────────────────────────────────────────

def _generate_svg(data):
    w = data.get("image_width", 800)
    h = data.get("image_height", 600)
    svg_parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        f'<style>',
        f'  .outer {{ stroke: #2a2520; fill: none; stroke-width: 4; }}',
        f'  .inner {{ stroke: #4a6580; fill: none; stroke-width: 2.5; }}',
        f'  .closet {{ stroke: #8050b0; fill: none; stroke-width: 1.5; stroke-dasharray: 4,2; }}',
        f'  .window {{ stroke: #40a0d0; fill: rgba(100,200,240,0.2); stroke-width: 1; }}',
        f'  .door {{ stroke: #c07040; fill: none; stroke-width: 1; }}',
        f'  .room {{ fill: rgba(100,150,200,0.05); stroke: #406080; stroke-width: 0.5; }}',
        f'  .room-label {{ font-family: Arial, sans-serif; font-size: 10px; fill: #607080; }}',
        f'  .fixture {{ stroke: #909090; fill: rgba(150,150,150,0.1); stroke-width: 0.8; }}',
        f'</style>',
    ]
    for room in data.get("rooms", []):
        if room.get("polygon") and len(room["polygon"]) > 2:
            pts = " ".join(f"{p[0]},{p[1]}" for p in room["polygon"])
            svg_parts.append(f'<polygon class="room" points="{pts}"/>')
        svg_parts.append(f'<text class="room-label" x="{room["cx"]}" y="{room["cy"]}" text-anchor="middle">{room.get("label","Room")}</text>')
    for seg in data.get("outer_walls", []):
        svg_parts.append(f'<line class="outer" x1="{seg["x1"]}" y1="{seg["y1"]}" x2="{seg["x2"]}" y2="{seg["y2"]}"/>')
    for seg in data.get("inner_walls", []):
        svg_parts.append(f'<line class="inner" x1="{seg["x1"]}" y1="{seg["y1"]}" x2="{seg["x2"]}" y2="{seg["y2"]}"/>')
    for seg in data.get("closets", []):
        svg_parts.append(f'<line class="closet" x1="{seg["x1"]}" y1="{seg["y1"]}" x2="{seg["x2"]}" y2="{seg["y2"]}"/>')
    for door in data.get("doors", []):
        svg_parts.append(f'<circle class="door" cx="{door["cx"]}" cy="{door["cy"]}" r="{door.get("radius_px",30)}"/>')
    for fix in data.get("fixtures", []):
        r = fix.get("radius", 8) or 8
        svg_parts.append(f'<circle class="fixture" cx="{fix["cx"]}" cy="{fix["cy"]}" r="{r}"/>')
    svg_parts.append('</svg>')
    return "\n".join(svg_parts)


def _generate_dxf(data):
    lines = ["0", "SECTION", "2", "HEADER", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]

    def add_line(x1, y1, x2, y2, layer="0"):
        lines.extend(["0", "LINE", "8", layer,
                      "10", str(round(x1, 3)), "20", str(round(-y1, 3)), "30", "0",
                      "11", str(round(x2, 3)), "21", str(round(-y2, 3)), "31", "0"])

    def add_circle(cx, cy, r, layer="0"):
        lines.extend(["0", "CIRCLE", "8", layer,
                      "10", str(round(cx, 3)), "20", str(round(-cy, 3)), "30", "0", "40", str(round(r, 3))])

    for seg in data.get("outer_walls", []): add_line(seg["x1"], seg["y1"], seg["x2"], seg["y2"], "OUTER_WALLS")
    for seg in data.get("inner_walls", []): add_line(seg["x1"], seg["y1"], seg["x2"], seg["y2"], "INNER_WALLS")
    for seg in data.get("closets", []): add_line(seg["x1"], seg["y1"], seg["x2"], seg["y2"], "CLOSETS")
    for win in data.get("windows", []): add_line(win["x1"], win["y1"], win["x2"], win["y2"], "WINDOWS")
    for door in data.get("doors", []): add_circle(door["cx"], door["cy"], door.get("radius_px", 30), "DOORS")
    for fix in data.get("fixtures", []):
        add_circle(fix["cx"], fix["cy"], fix.get("radius", 8) or 8, "FIXTURES")

    lines.extend(["0", "ENDSEC", "0", "EOF"])
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Demo floor plan generator
# ─────────────────────────────────────────────────────────────

def _generate_demo_plan(preset: str = "complex") -> np.ndarray:
    W, H = 740, 600
    img  = np.ones((H, W, 3), dtype=np.uint8) * 255

    def L(x1,y1,x2,y2,t):
        cv2.line(img,(x1,y1),(x2,y2),(18,18,18),t,cv2.LINE_AA)

    def win(x1,y1,x2,y2,off=4):
        dx,dy = x2-x1,y2-y1
        ln    = max(1,np.hypot(dx,dy))
        nx,ny = -dy/ln*off, dx/ln*off
        for ox,oy in [(nx,ny),(-nx,-ny)]:
            cv2.line(img,(int(x1+ox),int(y1+oy)),(int(x2+ox),int(y2+oy)),(40,40,40),1,cv2.LINE_AA)

    def door(cx,cy,r,a0,a1):
        cv2.ellipse(img,(cx,cy),(r,r),0,int(np.degrees(a0)),int(np.degrees(a1)),(25,25,25),1,cv2.LINE_AA)
        cv2.line(img,(cx,cy),(int(cx+r*np.cos(a0)),int(cy+r*np.sin(a0))),(25,25,25),1,cv2.LINE_AA)

    def toilet(cx, cy, r=12):
        cv2.ellipse(img, (cx, cy), (r, int(r*0.8)), 0, 0, 360, (30,30,30), 1, cv2.LINE_AA)
        cv2.rectangle(img, (cx-r, cy-int(r*1.5)), (cx+r, cy-int(r*0.8)), (30,30,30), 1, cv2.LINE_AA)

    def sink(cx, cy, r=8):
        cv2.circle(img, (cx, cy), r, (30,30,30), 1, cv2.LINE_AA)
        cv2.rectangle(img, (cx-r-3, cy-r-3), (cx+r+3, cy+r+3), (30,30,30), 1, cv2.LINE_AA)

    def bathtub(x1, y1, x2, y2):
        cv2.rectangle(img, (x1, y1), (x2, y2), (30,30,30), 1, cv2.LINE_AA)
        cv2.ellipse(img, ((x1+x2)//2, (y1+y2)//2),
                   ((x2-x1)//2-4, (y2-y1)//2-4), 0, 0, 360, (40,40,40), 1, cv2.LINE_AA)

    def label(x,y,txt):
        cv2.putText(img,txt,(x,y),cv2.FONT_HERSHEY_SIMPLEX,0.36,(185,185,185),1,cv2.LINE_AA)

    if preset == "simple":
        L(60,60,680,60,14);  L(680,60,680,540,14)
        L(60,540,680,540,14);L(60,60,60,540,14)
        win(150,60,300,60,4); win(450,60,600,60,4)
        win(680,150,680,300,4)
        door(60,300,50, -np.pi/2, 0)
        door(680,300,50, np.pi/2, np.pi)
        label(330,310,"OPEN PLAN")
        return img

    # Complex plan
    L(55,55,685,55,14); L(685,55,685,545,14)
    L(55,545,685,545,14); L(55,55,55,545,14)
    L(55,295,370,295,8)
    L(370,55,370,545,8)
    L(370,350,685,350,8)
    L(510,55,510,295,8)
    L(370,180,510,180,8)
    L(55,420,175,420,5)
    L(175,295,175,545,5)
    L(510,155,685,155,5)

    win(140,55,250,55,4); win(410,55,490,55,4); win(555,55,650,55,4)
    win(685,90,685,210,4); win(685,380,685,490,4)
    win(55,340,55,450,4); win(160,545,310,545,4); win(430,545,590,545,4)

    door(370,295,50, np.pi, np.pi*3/2)
    door(370,430,44, -np.pi/2, 0)
    door(215,295,42, 0, np.pi/2)
    door(510,210,40, -np.pi/2, 0)
    door(175,390,36, np.pi/2, np.pi)

    toilet(560, 310); sink(530, 290)
    bathtub(440, 270, 500, 340); sink(300, 430)

    label(195,180,"LIVING ROOM"); label(570,200,"BEDROOM 1")
    label(205,420,"KITCHEN"); label(530,455,"BEDROOM 2")
    label(525,315,"BATHROOM"); label(80,370,"CLOSET")

    return img


if __name__ == "__main__":
    port  = int(os.environ.get("PORT",  5050))
    debug = os.environ.get("DEBUG","true").lower() == "true"
    logger.info(f"FloorPlan3D v6 starting on port {port}  (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
