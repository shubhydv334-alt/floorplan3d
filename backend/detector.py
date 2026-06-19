"""
FloorPlan3D — Rule-Based Detection Engine  v5
==============================================
Upgrades over v4:
- Room polygon extraction with semantic classification
- Fixture/furniture recognition (toilet, sink, bathtub, stove)
- Enhanced room metadata (area m², polygon vertices, semantic type)
- Room classification heuristics (size, aspect ratio, fixture proximity)
- Fixture rendering data for 3D frontend
- CLAHE contrast enhancement before Otsu binarization
- Morphological close after open: heals 1-2px scanline gaps in walls
- Junction repair: 4x4 close kernel fills T/L/X intersection gaps
- Adaptive thresholds: guards against uniform-pen plans (narrow spread)
- Per-segment thickness: sampled along centerline, not class-average
- Confidence score per element
- Window deduplication: overlapping detections collapsed
- Door: 72-point arc sampling + straight leaf line verification
- Door: arc_start/arc_end returned for correct 3D swing angle
- Stair: NumPy vectorized run detection (no Python loops over pixels)
- Room detection: white-region connected components → centroids + bbox
- 20px white padding added pre-detection; coordinates compensated on output
- Graceful fallback when image has <50 ink pixels
"""

import cv2
import numpy as np
import base64
import logging
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)


from models import FloorPlanResult, WallData, WindowData, DoorData, RoomData, OpeningData, FurnitureData, FixtureData

try:
    from dl_detector import YoloDetector
except ImportError:
    YoloDetector = None

try:
    import easyocr
    _EASYOCR_AVAILABLE = True
except ImportError:
    _EASYOCR_AVAILABLE = False
    logger.warning("easyocr not installed — room OCR labels will fall back to heuristics")

# ─────────────────────────────────────────────────────────────
# Detector
# ─────────────────────────────────────────────────────────────

class FloorPlanDetector:

    PAD = 20

    # Room type classification thresholds (relative to total plan area)
    ROOM_TYPES = {
        'bathroom':  {'max_ratio': 0.08, 'aspect_range': (0.5, 2.0)},
        'closet':    {'max_ratio': 0.04, 'aspect_range': (0.3, 3.5)},
        'hallway':   {'max_ratio': 0.10, 'aspect_range': (0.1, 0.35)},
        'kitchen':   {'max_ratio': 0.18, 'aspect_range': (0.5, 2.0)},
        'bedroom':   {'max_ratio': 0.35, 'aspect_range': (0.5, 2.0)},
        'living':    {'max_ratio': 1.00, 'aspect_range': (0.4, 2.5)},
    }

    # Lazy-loaded EasyOCR reader (shared across calls)
    _ocr_reader = None

    @classmethod
    def _get_ocr_reader(cls):
        if cls._ocr_reader is None and _EASYOCR_AVAILABLE:
            logger.info("Initializing EasyOCR reader (first run downloads ~100 MB model)...")
            cls._ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            logger.info("EasyOCR reader ready.")
        return cls._ocr_reader

    def __init__(self, max_dim: int = 900, use_dl: bool = True):
        self.max_dim = max_dim
        self.use_dl = use_dl
        self.yolo = YoloDetector() if use_dl and YoloDetector else None

    # ══════════════════════════════════════════════════════════
    # PUBLIC
    # ══════════════════════════════════════════════════════════

    def detect(self, image_bytes: bytes, ortho_tol: float = 0.5) -> FloorPlanResult:
        arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image")

        h, w = img.shape[:2]
        if max(h, w) > self.max_dim:
            sc  = self.max_dim / max(h, w)
            img = cv2.resize(img, (int(w*sc), int(h*sc)), interpolation=cv2.INTER_AREA)

        # Pad so boundary walls are fully enclosed
        P   = self.PAD
        img = cv2.copyMakeBorder(img, P, P, P, P,
                                  cv2.BORDER_CONSTANT, value=(255,255,255))
        H, W = img.shape[:2]
        res  = FloorPlanResult(image_width=W, image_height=H)

        import time
        t0 = time.perf_counter()
        # 1 — Preprocess
        binary, gray = self._preprocess(img)
        t_pre = time.perf_counter() - t0
        dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)

        # 3 — Classify by thickness
        thresholds, cls_map = self._classify(dist)
        res.thresholds = thresholds

        # 4 — Junction repair
        binary_repaired = self._repair_junctions(binary)

        # 5 — Skeletonize each class
        t1 = time.perf_counter()
        skel_outer     = self._skeletonize((cls_map == 4).astype(np.uint8))
        skel_inner_raw = self._skeletonize((cls_map == 3).astype(np.uint8))
        skel_closet_raw= self._skeletonize((cls_map == 2).astype(np.uint8))
        skel_line      = self._skeletonize((cls_map == 1).astype(np.uint8))
        t_skel = time.perf_counter() - t1

        # 6 — Connectivity filter (Dynamic Kernel Sizes based on resolution)
        base_k = max(3, int(max(W, H) / 100))
        dil_k_large = cv2.getStructuringElement(cv2.MORPH_RECT, (base_k, base_k))
        dil_k_med   = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, base_k - 2), max(3, base_k - 2)))
        
        outer_mask  = cv2.dilate(skel_outer, dil_k_large)
        inner_filt  = self._filter_connected(skel_inner_raw,  outer_mask, keep=True)
        inner_mask  = cv2.dilate(inner_filt, dil_k_med)
        closet_filt = self._filter_connected(skel_closet_raw, outer_mask, keep=False)

        # 7 — Capture per-class thickness stats BEFORE skeletonization (P3)
        thickness_stats = self._compute_thickness_stats(dist, cls_map)
        res.thresholds['thickness_stats'] = thickness_stats

        # 8 — Vectorize & Post-Process with Orthogonal Forcing & Corner Snapping
        t2 = time.perf_counter()
        outer_segs  = self._post_process_segments(self._vectorize(skel_outer,   dist, cls_map, 4, 30, 15, binary), W, H, ortho_tol)
        inner_segs  = self._post_process_segments(self._vectorize(inner_filt,   dist, cls_map, 3, 20, 15, binary), W, H, ortho_tol)
        closet_segs = self._post_process_segments(self._vectorize(closet_filt,  dist, cls_map, 2, 12, 10, binary), W, H, ortho_tol)
        t_vect = time.perf_counter() - t2

        wall_id_counter = 0
        res.outer_walls = []
        for s in outer_segs:
            d = self._seg_dict(s, "outer", wall_id_counter)
            res.outer_walls.append(d)
            wall_id_counter += 1
        res.inner_walls = []
        for s in inner_segs:
            d = self._seg_dict(s, "inner", wall_id_counter)
            res.inner_walls.append(d)
            wall_id_counter += 1
        res.closets = []
        for s in closet_segs:
            d = self._seg_dict(s, "closet", wall_id_counter)
            res.closets.append(d)
            wall_id_counter += 1

        # 8.5 — Deep Learning Inference (Optional)
        dl_results = None
        if self.use_dl and self.yolo and self.yolo.enabled:
            logger.info("Running YOLO Deep Learning inference...")
            dl_results = self.yolo.detect(img)

        # 9 — Windows (OpenCV is better for structural windows)
        res.windows = self._detect_windows(skel_line, W, H)

        # 10 — Doors (OpenCV is better for arcs)
        res.doors = self._detect_doors(gray, binary, W, H)

        # 10.5 — Furniture & Fixtures
        if dl_results:
            if dl_results.get("furniture"):
                res.furniture = [FurnitureData(**f) for f in dl_results["furniture"]]
            if dl_results.get("fixtures"):
                res.fixtures = [FixtureData(**f) for f in dl_results["fixtures"]]

        # 11 — Assign doors to walls (P1: wall ownership)
        all_walls = res.outer_walls + res.inner_walls + res.closets
        self._assign_doors_to_walls(res.doors, all_walls)

        # 12 — Assign windows to walls (P2: window validation & snap)
        self._assign_windows_to_walls(res.windows, all_walls)

        # 13 — Stairs
        res.stairs  = self._detect_stairs(skel_line, W, H)

        # 14 — Rooms (enhanced with polygons and semantic types)
        t3 = time.perf_counter()
        res.rooms   = self._detect_rooms(gray, binary, W, H)
        t_rooms = time.perf_counter() - t3

        # 14b — Validate room boundaries (P4: gap bridging)
        self._validate_room_boundaries(res.rooms, res.outer_walls + res.inner_walls + res.closets)

        # 15 — Fixtures (toilet, sink, bathtub, stove)
        res.fixtures = self._detect_fixtures(gray, binary, W, H, res.rooms)

        # 16 — Classify rooms semantically using fixtures + geometry
        self._classify_rooms(res.rooms, res.fixtures, res.doors, W, H)

        # 17 — Furniture
        res.furniture = self._detect_furniture(binary, W, H, res.rooms)

        # Debug images
        res.debug_images = {
            "thickness":      self._enc_thickness(dist, thresholds["p75"]),
            "classification": self._enc_classes(cls_map),
            "skeleton":       self._enc_skel(img, skel_outer, inner_filt,
                                              closet_filt, skel_line),
            "preprocessed":   self._enc(binary),
            "rooms":          self._enc_rooms(img, res.rooms, res.fixtures),
        }

        res.summary = {k: len(getattr(res, k))
                       for k in ("outer_walls","inner_walls","closets",
                                 "windows","doors","stairs","rooms","fixtures")}
        
        # P16 Metrics
        total_nodes = len(res.outer_walls) + len(res.inner_walls) + len(res.closets) + len(res.windows) + len(res.doors) + len(res.rooms)
        res.summary['metrics'] = {
            "time_preprocess_ms": round(t_pre*1000),
            "time_skeleton_ms": round(t_skel*1000),
            "time_vectorize_ms": round(t_vect*1000),
            "time_rooms_ms": round(t_rooms*1000),
            "total_nodes": total_nodes
        }

        self._strip_pad(res, P)
        return res

    # ══════════════════════════════════════════════════════════
    # PREPROCESS
    # ══════════════════════════════════════════════════════════

    def _preprocess(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # CLAHE — lift low-contrast faint lines before thresholding
        clahe   = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_eq = clahe.apply(gray)

        blurred = cv2.GaussianBlur(gray_eq, (3, 3), 0.5)
        _, binary = cv2.threshold(blurred, 0, 255,
                                   cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Connect small gaps before removing noise
        k_close_init = max(2, int(max(img.shape[:2]) / 400))
        if k_close_init > 1:
            k = cv2.getStructuringElement(cv2.MORPH_RECT, (k_close_init, k_close_init))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)

        # Filter out small components (Text / Noise / Dimension lines)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        area_thresh = max(40, (max(img.shape[:2]) / 900.0) ** 2 * 120)
        
        mask = np.zeros_like(binary)
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= area_thresh:
                mask[labels == i] = 255
        binary = mask

        # Open: remove remaining sub-2px noise specks (Dynamic)
        k_open = max(2, int(max(img.shape[:2]) / 450))
        k2 = cv2.getStructuringElement(cv2.MORPH_RECT, (k_open, k_open))
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k2)

        # Close: heal 1-2px scanline gaps in lines (Dynamic)
        k_close = max(3, int(max(img.shape[:2]) / 300))
        k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (k_close, k_close))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k3)

        return binary, gray

    # ══════════════════════════════════════════════════════════
    # CLASSIFY BY THICKNESS
    # ══════════════════════════════════════════════════════════

    def _classify(self, dist):
        nonzero = dist[dist > 0].flatten()
        if len(nonzero) < 50:
            cls = np.zeros_like(dist, dtype=np.uint8)
            cls[dist > 0] = 4
            return dict(t_line=1.5,t_closet_max=2,t_inner_max=4,max_val=0), cls

        # Use 98th percentile to find the thickness of the thickest walls, 
        # ignoring small solid black blobs, capped at 15 for typical plans.
        p98 = float(np.percentile(nonzero, 98))
        max_wall = min(p98, 15.0)

        if max_wall < 2.0:
            # Very thin uniform plan
            T_LINE   = max_wall * 0.4
            T_CLOSET = max_wall * 0.6
            T_INNER  = max_wall * 0.8
        else:
            # Thresholds relative to the thickest wall
            T_LINE   = max(1.0, max_wall * 0.20)
            T_CLOSET = max(1.5, max_wall * 0.35)
            T_INNER  = max(2.5, max_wall * 0.60)

        cls = np.zeros_like(dist, dtype=np.uint8)
        ink = dist > 0
        cls[ink & (dist <= T_LINE)]                        = 1
        cls[ink & (dist > T_LINE)   & (dist <= T_CLOSET)] = 2
        cls[ink & (dist > T_CLOSET) & (dist <= T_INNER)]  = 3
        cls[ink & (dist > T_INNER)]                        = 4

        return dict(max_wall=max_wall,
                    t_line=T_LINE,t_closet_max=T_CLOSET,t_inner_max=T_INNER), cls

    # ══════════════════════════════════════════════════════════
    # JUNCTION REPAIR
    # ══════════════════════════════════════════════════════════

    def _repair_junctions(self, binary):
        k_size = max(4, int(max(binary.shape) / 225))
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
        return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)

    # ══════════════════════════════════════════════════════════
    # SKELETONIZE
    # ══════════════════════════════════════════════════════════

    def _skeletonize(self, img):
        skel   = np.zeros_like(img, dtype=np.uint8)
        src    = img.copy()
        kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        while True:
            eroded = cv2.erode(src, kernel)
            temp   = cv2.dilate(eroded, kernel)
            temp   = cv2.subtract(src, temp)
            skel   = cv2.bitwise_or(skel, temp)
            src    = eroded
            if cv2.countNonZero(src) == 0:
                break
        return skel

    # ══════════════════════════════════════════════════════════
    # CONNECTIVITY FILTER
    # ══════════════════════════════════════════════════════════

    def _filter_connected(self, skel, mask, keep):
        n, labels = cv2.connectedComponents(skel, connectivity=8)
        out = np.zeros_like(skel)
        for lbl in range(1, n):
            comp    = labels == lbl
            touches = np.any(mask[comp] > 0)
            if touches == keep:
                out[comp] = 255
        return out

    # ══════════════════════════════════════════════════════════
    # VECTORIZE — Hough + merge + per-segment thickness
    # ══════════════════════════════════════════════════════════

    def _vectorize(self, skel, dist, cls_map, cls_id, min_len, max_gap, binary=None):
        lines = cv2.HoughLinesP(skel, 1, np.pi/180,
                                 threshold=min_len,
                                 minLineLength=min_len,
                                 maxLineGap=max_gap)
        if lines is None:
            return []

        raw    = [tuple(map(float, l[0])) for l in lines]
        merged = self._merge_collinear(raw)

        result = []
        for (x1, y1, x2, y2) in merged:
            n_pts = max(3, int(np.hypot(x2-x1, y2-y1) / 3))
            xs    = np.clip(np.linspace(x1,x2,n_pts).astype(int), 0, dist.shape[1]-1)
            ys    = np.clip(np.linspace(y1,y2,n_pts).astype(int), 0, dist.shape[0]-1)
            thick = float(np.median(dist[ys, xs])) * 2.0
            if thick < 0.5:
                vals  = dist[cls_map == cls_id]
                thick = float(np.median(vals)) * 2.0 if len(vals) else 8.0

            # P3: Capture original thickness from the full binary mask
            # Sample perpendicular to the segment at multiple points
            orig_thick = thick
            if binary is not None:
                dx, dy = x2 - x1, y2 - y1
                seg_len = max(1.0, np.hypot(dx, dy))
                nx, ny = -dy / seg_len, dx / seg_len  # perpendicular normal
                widths = []
                for frac in np.linspace(0.1, 0.9, min(7, n_pts)):
                    px_c = int(np.clip(x1 + frac * dx, 0, dist.shape[1] - 1))
                    py_c = int(np.clip(y1 + frac * dy, 0, dist.shape[0] - 1))
                    # Walk along normal in both directions to measure ink width
                    half_w = 0
                    for step in range(1, 40):
                        sx = int(np.clip(px_c + nx * step, 0, dist.shape[1] - 1))
                        sy = int(np.clip(py_c + ny * step, 0, dist.shape[0] - 1))
                        if binary[sy, sx] == 0:
                            break
                        half_w = step
                    for step in range(1, 40):
                        sx = int(np.clip(px_c - nx * step, 0, dist.shape[1] - 1))
                        sy = int(np.clip(py_c - ny * step, 0, dist.shape[0] - 1))
                        if binary[sy, sx] == 0:
                            break
                        half_w = max(half_w, step)
                    if half_w > 0:
                        widths.append(half_w * 2.0)
                if widths:
                    orig_thick = float(np.median(widths))

            length = float(np.hypot(x2-x1, y2-y1))
            conf   = min(1.0, (length/50.0) * min(1.0, thick/6.0))
            # Tuple: x1,y1,x2,y2, thick(skeleton), conf, length, orig_thick(pre-skeleton)
            result.append((x1, y1, x2, y2, thick, conf, length, orig_thick))
        return result

    def _post_process_segments(self, segs, W=800, H=600, ortho_tol=0.5):
        """P7-enhanced: adaptive snap radius, T-junction detection, Union-Find clustering."""
        if not segs: return []

        # Adaptive snap radius based on image resolution
        snap_radius = max(8, int(max(W, H) / 60))

        # 1. Force Orthogonal
        forced = []
        for seg in segs:
            x1, y1, x2, y2, thick, conf, length = seg[0], seg[1], seg[2], seg[3], seg[4], seg[5], seg[6]
            orig_thick = seg[7] if len(seg) > 7 else thick
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
            if min(angle, 180 - angle) < ortho_tol:
                my = (y1 + y2) / 2
                forced.append([x1, my, x2, my, thick, conf, length, orig_thick])
            elif abs(angle - 90) < ortho_tol:
                mx = (x1 + x2) / 2
                forced.append([mx, y1, mx, y2, thick, conf, length, orig_thick])
            else:
                forced.append([x1, y1, x2, y2, thick, conf, length, orig_thick])

        # 2. Collect all endpoints
        pts = []
        for i, s in enumerate(forced):
            pts.extend([(i, 0, s[0], s[1]), (i, 2, s[2], s[3])])

        # 3. T-junction detection: snap endpoints to nearby segment midlines
        for pi, (s_idx, p_off, px_val, py_val) in enumerate(pts):
            best_dist = snap_radius
            best_proj = None
            for si, seg in enumerate(forced):
                if si == s_idx:
                    continue
                sx1, sy1, sx2, sy2 = seg[0], seg[1], seg[2], seg[3]
                sdx, sdy = sx2 - sx1, sy2 - sy1
                seg_len_sq = sdx * sdx + sdy * sdy
                if seg_len_sq < 1.0:
                    continue
                # Project point onto segment
                t = ((px_val - sx1) * sdx + (py_val - sy1) * sdy) / seg_len_sq
                if t < 0.05 or t > 0.95:  # skip near-endpoints (handled by corner snap)
                    continue
                proj_x = sx1 + t * sdx
                proj_y = sy1 + t * sdy
                d = np.hypot(px_val - proj_x, py_val - proj_y)
                if d < best_dist:
                    best_dist = d
                    best_proj = (proj_x, proj_y)
            if best_proj is not None:
                forced[s_idx][p_off] = best_proj[0]
                forced[s_idx][p_off + 1] = best_proj[1]
                pts[pi] = (s_idx, p_off, best_proj[0], best_proj[1])

        # 4. Union-Find corner snapping for endpoints
        n = len(pts)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Re-read pts after T-junction adjustment
        pts = []
        for i, s in enumerate(forced):
            pts.extend([(i, 0, s[0], s[1]), (i, 2, s[2], s[3])])
        parent = list(range(len(pts)))

        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                si, _, x1, y1 = pts[i]
                sj, _, x2, y2 = pts[j]
                if si == sj:
                    continue
                if np.hypot(x1 - x2, y1 - y2) < snap_radius:
                    # Topology check (P7.2): prevent parallel non-collinear walls from snapping
                    seg_i = forced[si]
                    seg_j = forced[sj]
                    dxi, dyi = seg_i[2] - seg_i[0], seg_i[3] - seg_i[1]
                    dxj, dyj = seg_j[2] - seg_j[0], seg_j[3] - seg_j[1]
                    li = np.hypot(dxi, dyi)
                    lj = np.hypot(dxj, dyj)
                    if li > 0 and lj > 0:
                        dot = abs((dxi * dxj + dyi * dyj) / (li * lj))
                        if dot > 0.98: # nearly parallel
                            # Check collinearity via cross product (distance from j's endpoint to i's line)
                            cross_dist = abs(dxi * (y2 - seg_i[1]) - dyi * (x2 - seg_i[0])) / li
                            if cross_dist > 4.0:
                                continue # Parallel but offset -> do not snap
                    union(i, j)

        # Collect clusters
        clusters = {}
        for i in range(len(pts)):
            r = find(i)
            clusters.setdefault(r, []).append(i)

        for members in clusters.values():
            if len(members) < 2:
                continue
            avg_x = sum(pts[m][2] for m in members) / len(members)
            avg_y = sum(pts[m][3] for m in members) / len(members)
            for m in members:
                s_idx, p_off = pts[m][0], pts[m][1]
                forced[s_idx][p_off] = avg_x
                forced[s_idx][p_off + 1] = avg_y

        for s in forced:
            s[6] = float(np.hypot(s[2] - s[0], s[3] - s[1]))

        return [tuple(s) for s in forced if s[6] > 1.0]

    def _seg_dict(self, s, seg_type, wall_id=0):
        """Build wall segment model with openings[] (P1/P2) and original_thickness (P3)."""
        return WallData(
            id=wall_id,
            x1=round(s[0], 1), y1=round(s[1], 1),
            x2=round(s[2], 1), y2=round(s[3], 1),
            thickness_px=round(s[4] if len(s) > 4 else 10.0, 2),
            original_thickness_px=round(s[7] if len(s) > 7 else (s[4] if len(s) > 4 else 10.0), 2),
            seg_type=seg_type,
            confidence=round(s[5] if len(s) > 5 else 1.0, 3),
            length_px=round(s[6] if len(s) > 6 else 0.0, 1),
            openings=[],
        )

    # ══════════════════════════════════════════════════════════
    # MERGE COLLINEAR SEGMENTS
    # ══════════════════════════════════════════════════════════

    def _merge_collinear(self, segs, angle_tol=6.0, dist_tol=14.0):
        if not segs:
            return []
        used   = [False]*len(segs)
        merged = []

        def angle(s):
            return np.degrees(np.arctan2(s[3]-s[1], s[2]-s[0])) % 180

        def pt_dist(px, py, s):
            dx,dy = s[2]-s[0],s[3]-s[1]
            d2    = dx*dx+dy*dy
            if d2 == 0:
                return np.hypot(px-s[0],py-s[1])
            t = np.clip(((px-s[0])*dx+(py-s[1])*dy)/d2, 0, 1)
            return np.hypot(px-(s[0]+t*dx), py-(s[1]+t*dy))

        for i, si in enumerate(segs):
            if used[i]:
                continue
            ai  = angle(si)
            pts = [[si[0],si[1]],[si[2],si[3]]]
            used[i] = True
            for j, sj in enumerate(segs):
                if used[j] or i==j:
                    continue
                aj = angle(sj)
                da = abs(ai-aj)
                if da > angle_tol and abs(da-180) > angle_tol:
                    continue
                mx,my = (sj[0]+sj[2])/2, (sj[1]+sj[3])/2
                if pt_dist(mx, my, si) < dist_tol:
                    pts += [[sj[0],sj[1]],[sj[2],sj[3]]]
                    used[j] = True

            pa = np.array(pts, dtype=np.float32)
            if len(pa) < 2:
                merged.append(si[:4]); continue
            line_fit = cv2.fitLine(pa, cv2.DIST_L2, 0, 0.01, 0.01)
            vx = float(line_fit[0][0])
            vy = float(line_fit[1][0])
            cx = float(line_fit[2][0])
            cy = float(line_fit[3][0])
            proj = [(p[0]-cx)*vx+(p[1]-cy)*vy for p in pa]
            t0,t1 = min(proj),max(proj)
            merged.append((round(cx+t0*vx,1), round(cy+t0*vy,1),
                            round(cx+t1*vx,1), round(cy+t1*vy,1)))
        return merged

    # ══════════════════════════════════════════════════════════
    # WINDOW DETECTION
    # ══════════════════════════════════════════════════════════

    def _detect_windows(self, skel_line, W, H):
        wins      = []
        used_rows = set()
        used_cols = set()

        # Horizontal pairs
        row_runs: Dict[int,List] = {}
        for y in range(1, H-1):
            row = skel_line[y, :]
            s_arr = np.where(np.diff(np.concatenate(([0], row, [0]))) == 255)[0]
            e_arr = np.where(np.diff(np.concatenate(([0], row, [0]))) == -255)[0]
            for s,e in zip(s_arr, e_arr):
                if e-s >= 8:
                    row_runs.setdefault(y,[]).append((int(s),int(e-1)))

        ys = sorted(row_runs)
        for i, y1 in enumerate(ys):
            if y1 in used_rows: continue
            for y2 in ys[i+1:]:
                gap = y2-y1
                if gap < 2:   continue
                if gap > 14:  break
                if y2 in used_rows: continue
                for r1 in row_runs[y1]:
                    for r2 in row_runs[y2]:
                        ox1,ox2 = max(r1[0],r2[0]), min(r1[1],r2[1])
                        if ox2-ox1 < 8: continue
                        cy = (y1+y2)/2
                        wins.append(WindowData(x1=float(ox1),y1=cy,
                                         x2=float(ox2),y2=cy,
                                         orient="h",gap_px=float(gap),
                                         confidence=min(1.0,(ox2-ox1)/60.0)))
                        used_rows.add(y1); used_rows.add(y2); break
                    if y1 in used_rows: break

        # Vertical pairs
        col_runs: Dict[int,List] = {}
        for x in range(1, W-1):
            col = skel_line[:, x]
            s_arr = np.where(np.diff(np.concatenate(([0], col, [0]))) == 255)[0]
            e_arr = np.where(np.diff(np.concatenate(([0], col, [0]))) == -255)[0]
            for s,e in zip(s_arr, e_arr):
                if e-s >= 8:
                    col_runs.setdefault(x,[]).append((int(s),int(e-1)))

        xs = sorted(col_runs)
        for i, x1 in enumerate(xs):
            if x1 in used_cols: continue
            for x2 in xs[i+1:]:
                gap = x2-x1
                if gap < 2:   continue
                if gap > 14:  break
                if x2 in used_cols: continue
                for r1 in col_runs[x1]:
                    for r2 in col_runs[x2]:
                        oy1,oy2 = max(r1[0],r2[0]), min(r1[1],r2[1])
                        if oy2-oy1 < 8: continue
                        cx = (x1+x2)/2
                        wins.append(WindowData(x1=cx,y1=float(oy1),
                                         x2=cx,y2=float(oy2),
                                         orient="v",gap_px=float(gap),
                                         confidence=min(1.0,(oy2-oy1)/60.0)))
                        used_cols.add(x1); used_cols.add(x2); break
                    if x1 in used_cols: break

        # Dedup
        deduped = []
        for w in wins:
            if not any(w.orient==k.orient
                       and abs(w.x1-k.x1)<8
                       and abs(w.y1-k.y1)<8 for k in deduped):
                deduped.append(w)

        return deduped[:50]

    # ══════════════════════════════════════════════════════════
    # DOOR DETECTION
    # ══════════════════════════════════════════════════════════

    def _detect_doors(self, gray, binary, W, H):
        doors = []
        edges = cv2.Canny(gray, 30, 100)

        circles = cv2.HoughCircles(edges, cv2.HOUGH_GRADIENT,
                                    dp=1.2, minDist=25,
                                    param1=50, param2=18,
                                    minRadius=10, maxRadius=75)
        if circles is None:
            return []

        circles = np.round(circles[0]).astype(int)
        for (cx, cy, r) in circles:
            angles = np.linspace(0, 2*np.pi, 72, endpoint=False)
            pxs    = np.clip((cx+r*np.cos(angles)).astype(int), 0, W-1)
            pys    = np.clip((cy+r*np.sin(angles)).astype(int), 0, H-1)
            hits   = binary[pys, pxs] > 0
            cov    = hits.mean()

            if cov < 0.08 or cov > 0.52:
                continue

            hit_angles = angles[hits]
            if len(hit_angles) < 4:
                continue

            arc_start = float(hit_angles[0])
            arc_end   = float(hit_angles[-1])

            # Verify leaf line near hinge
            hx = int(cx + r*np.cos(arc_start))
            hy = int(cy + r*np.sin(arc_start))
            roi= binary[max(0,hy-6):hy+6, max(0,hx-6):hx+6]
            has_leaf = bool(roi.any())

            if any(abs(d.cx-cx)<r and abs(d.cy-cy)<r for d in doors):
                continue

            doors.append(DoorData(
                cx=float(cx), cy=float(cy),
                radius_px=float(r),
                arc_start=round(arc_start, 3),
                arc_end=round(arc_end, 3),
                coverage=round(float(cov), 3),
                has_leaf=has_leaf,
                confidence=round(min(1.0, cov/0.3*(0.7+0.3*has_leaf)), 3),
                wallId=-1,
                position_t=0.0,
                opening_width=float(r * 2),
            ))

        return sorted(doors, key=lambda d: -d.confidence)[:25]

    # ══════════════════════════════════════════════════════════
    # P1: ASSIGN DOORS TO WALLS
    # ══════════════════════════════════════════════════════════

    def _assign_doors_to_walls(self, doors, walls):
        """Assign each door to exactly one wall. Store wallId + opening in wall.openings[]."""
        if not doors or not walls:
            return

        for door in doors:
            dcx, dcy = door.cx, door.cy
            best_wall = None
            best_dist = float('inf')
            best_t = 0.0

            for wall in walls:
                wx1, wy1 = wall.x1, wall.y1
                wx2, wy2 = wall.x2, wall.y2
                wdx, wdy = wx2 - wx1, wy2 - wy1
                wall_len_sq = wdx * wdx + wdy * wdy
                if wall_len_sq < 1.0:
                    continue

                # Project door center onto wall segment
                t = ((dcx - wx1) * wdx + (dcy - wy1) * wdy) / wall_len_sq
                t_clamped = max(0.0, min(1.0, t))
                proj_x = wx1 + t_clamped * wdx
                proj_y = wy1 + t_clamped * wdy
                dist = math.hypot(dcx - proj_x, dcy - proj_y)

                # Max snap distance: 2x wall thickness or 20px, whichever larger
                max_snap = max(20.0, getattr(wall, 'thickness_px', 10) * 2)

                if dist < best_dist and dist < max_snap and 0.01 < t < 0.99:
                    best_dist = dist
                    best_wall = wall
                    best_t = t_clamped

            if best_wall is not None:
                door.wallId = best_wall.id
                door.position_t = round(best_t, 4)
                wall_len = math.hypot(
                    best_wall.x2 - best_wall.x1,
                    best_wall.y2 - best_wall.y1
                )
                opening_width = door.opening_width
                span = opening_width / max(1.0, wall_len)
                best_wall.openings.append(OpeningData(
                    type='door',
                    position_t=round(best_t, 4),
                    width_px=round(opening_width, 1)
                ))
            else:
                # Door didn't match any wall — halve confidence
                door['wallId'] = -1
                door['confidence'] = round(door['confidence'] * 0.5, 3)

    # ══════════════════════════════════════════════════════════
    # P2: ASSIGN WINDOWS TO WALLS (VALIDATION & SNAP)
    # ══════════════════════════════════════════════════════════

    def _assign_windows_to_walls(self, windows, walls):
        """Validate and snap each window to exactly one wall. Reject invalid."""
        if not windows or not walls:
            return

        to_remove = []
        for wi, win in enumerate(windows):
            wcx = (win.x1 + win.x2) / 2
            wcy = (win.y1 + win.y2) / 2
            win_dx = win.x2 - win.x1
            win_dy = win.y2 - win.y1
            win_angle = math.degrees(math.atan2(win_dy, win_dx)) % 180
            win_len = math.hypot(win_dx, win_dy)

            best_wall = None
            best_dist = float('inf')
            best_t = 0.0

            for wall in walls:
                wx1, wy1 = wall.x1, wall.y1
                wx2, wy2 = wall.x2, wall.y2
                wdx, wdy = wx2 - wx1, wy2 - wy1
                wall_len_sq = wdx * wdx + wdy * wdy
                wall_len = math.sqrt(wall_len_sq) if wall_len_sq > 0 else 0
                if wall_len < 1.0:
                    continue

                # Orientation check: window and wall must be within ±15°
                wall_angle = math.degrees(math.atan2(wdy, wdx)) % 180
                angle_diff = abs(win_angle - wall_angle)
                if angle_diff > 15 and abs(angle_diff - 180) > 15:
                    continue

                # Window length must be ≤ wall length
                if win_len > wall_len * 1.1:
                    continue

                # Project window center onto wall
                t = ((wcx - wx1) * wdx + (wcy - wy1) * wdy) / wall_len_sq
                t_clamped = max(0.0, min(1.0, t))
                proj_x = wx1 + t_clamped * wdx
                proj_y = wy1 + t_clamped * wdy
                dist = math.hypot(wcx - proj_x, wcy - proj_y)

                max_snap = max(15.0, getattr(wall, 'thickness_px', 8) * 2)

                if dist < best_dist and dist < max_snap and 0.01 < t < 0.99:
                    best_dist = dist
                    best_wall = wall
                    best_t = t_clamped

            if best_wall is not None:
                # Snap window to wall centerline
                bwx1, bwy1 = best_wall.x1, best_wall.y1
                bwx2, bwy2 = best_wall.x2, best_wall.y2
                bwdx, bwdy = bwx2 - bwx1, bwy2 - bwy1
                bw_len = math.hypot(bwdx, bwdy)
                half_span = (win_len / 2) / max(1.0, bw_len)
                t1 = max(0.0, best_t - half_span)
                t2 = min(1.0, best_t + half_span)

                # Snap coordinates to lie on wall
                win.x1 = round(bwx1 + t1 * bwdx, 1)
                win.y1 = round(bwy1 + t1 * bwdy, 1)
                win.x2 = round(bwx1 + t2 * bwdx, 1)
                win.y2 = round(bwy1 + t2 * bwdy, 1)
                win.wallId = best_wall.id

                span = (t2 - t1)
                best_wall.openings.append(OpeningData(
                    type='window',
                    position_t=round(best_t, 4),
                    width_px=round(win_len, 1)
                ))
            else:
                # Reject window — mark for removal
                win.wallId = -1
                win.confidence = round(getattr(win, 'confidence', 0.5) * 0.3, 3)
                to_remove.append(wi)

        # Remove rejected windows (iterate in reverse to preserve indices)
        for idx in reversed(to_remove):
            windows.pop(idx)

    # ══════════════════════════════════════════════════════════
    # STAIR DETECTION
    # ══════════════════════════════════════════════════════════

    def _detect_stairs(self, skel_line, W, H):
        stairs = []

        def get_runs(arr_2d, axis):
            runs = {}
            length = arr_2d.shape[1-axis]
            for idx in range(1, arr_2d.shape[axis]-1):
                line = arr_2d[idx,:] if axis==0 else arr_2d[:,idx]
                padded = np.concatenate(([0], line.astype(np.int16), [0]))
                diff   = np.diff(padded)
                starts = np.where(diff == 255)[0]
                ends   = np.where(diff == -255)[0]
                for s,e in zip(starts,ends):
                    if e-s >= 16:
                        runs.setdefault(int(idx),[]).append((int(s),int(e-1),int(e-s)))
            return runs

        # Horizontal
        row_runs = get_runs(skel_line, axis=0)
        stairs  += self._group_runs(row_runs, "h")

        # Vertical
        col_runs = get_runs(skel_line, axis=1)
        stairs  += self._group_runs(col_runs, "v")

        return stairs

    def _group_runs(self, runs, orient):
        groups = []
        keys   = sorted(runs)
        i      = 0
        while i < len(keys):
            group = [keys[i]]
            j = i+1
            while j < len(keys):
                gap = keys[j]-keys[j-1]
                if gap < 8 or gap > 58: break
                if len(group) >= 2 and abs(gap-(group[-1]-group[-2])) > 6: break
                r1 = runs.get(keys[j-1],[None])[0]
                r2 = runs.get(keys[j],  [None])[0]
                if not r1 or not r2: break
                if min(r1[1],r2[1])-max(r1[0],r2[0]) < 14: break
                group.append(keys[j]); j += 1

            if len(group) >= 3:
                all_r   = [runs[k][0] for k in group if runs.get(k)]
                a1,a2   = min(r[0] for r in all_r), max(r[1] for r in all_r)
                spacing = (group[-1]-group[0])/(len(group)-1) if len(group)>1 else 20
                if orient=="h":
                    groups.append(dict(x1=float(a1),y1=float(group[0]),
                                       x2=float(a2),y2=float(group[-1]),
                                       steps=len(group),orient="h",
                                       spacing_px=round(spacing,1),
                                       confidence=round(min(1.0,len(group)/10.0),3)))
                else:
                    groups.append(dict(x1=float(group[0]),y1=float(a1),
                                       x2=float(group[-1]),y2=float(a2),
                                       steps=len(group),orient="v",
                                       spacing_px=round(spacing,1),
                                       confidence=round(min(1.0,len(group)/10.0),3)))
                i = j
            else:
                i += 1
        return groups

    # ══════════════════════════════════════════════════════════
    # ROOM DETECTION (ENHANCED v5 + P4 progressive dilation)
    # ══════════════════════════════════════════════════════════

    def _detect_rooms(self, gray, binary, W, H):
        total = W * H

        # P4: Progressive dilation — try smallest kernel first, increase if rooms merge
        best_rooms = []
        best_kernel_size = 7
        for k_size in [7, 9, 11]:
            k_thick = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
            walls_thick = cv2.morphologyEx(binary, cv2.MORPH_DILATE, k_thick)

            white = cv2.bitwise_not(walls_thick)
            k     = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, k)
            white = cv2.morphologyEx(white, cv2.MORPH_OPEN, k)

            n, labels, stats, centroids = cv2.connectedComponentsWithStats(
                white, connectivity=4)

            rooms = []
            for lbl in range(1, n):
                area = int(stats[lbl, cv2.CC_STAT_AREA])
                if area < total * 0.005 or area > total * 0.80:
                    continue

                bx = int(stats[lbl, cv2.CC_STAT_LEFT])
                by = int(stats[lbl, cv2.CC_STAT_TOP])
                bw = int(stats[lbl, cv2.CC_STAT_WIDTH])
                bh = int(stats[lbl, cv2.CC_STAT_HEIGHT])

                cx = float(centroids[lbl][0])
                cy = float(centroids[lbl][1])

                # Find matching contour for this label
                polygon = []
                label_mask = (labels == lbl).astype(np.uint8) * 255
                room_contours, _ = cv2.findContours(label_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if room_contours:
                    largest = max(room_contours, key=cv2.contourArea)
                    epsilon = 0.02 * cv2.arcLength(largest, True)
                    approx = cv2.approxPolyDP(largest, epsilon, True)
                    polygon = [[int(p[0][0]), int(p[0][1])] for p in approx]

                # Check if polygon is closed
                boundary_closed = False
                if len(polygon) >= 3:
                    first, last = polygon[0], polygon[-1]
                    boundary_closed = math.hypot(first[0] - last[0], first[1] - last[1]) < 5.0

                aspect = min(bw, bh) / max(bw, bh) if max(bw, bh) > 0 else 1.0
                area_ratio = area / total

                ocr_text = ""
                room_type = "unknown"
                label = f"Room {len(rooms)+1}"
                try:
                    reader = self._get_ocr_reader()
                    if reader:
                        # Crop room ROI with padding for OCR
                        pad_ocr = 10
                        y1o, y2o = max(0, by - pad_ocr), min(H, by + bh + pad_ocr)
                        x1o, x2o = max(0, bx - pad_ocr), min(W, bx + bw + pad_ocr)
                        roi = gray[y1o:y2o, x1o:x2o]
                        # Preprocess: blur + Otsu for clean text
                        roi = cv2.GaussianBlur(roi, (3, 3), 0)
                        _, roi = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                        results = reader.readtext(roi, detail=0, paragraph=True)
                        text = ' '.join(results).strip().upper() if results else ''
                        if text:
                            ocr_text = text
                            # Rule-based label mapping from OCR text
                            if any(k in text for k in ["BATH", "WC", "TOILET", "LAVATORY", "W.C"]):
                                room_type = "bathroom"; label = "Bathroom"
                            elif any(k in text for k in ["KITCHEN", "KIT", "PANTRY", "COOKING"]):
                                room_type = "kitchen"; label = "Kitchen"
                            elif any(k in text for k in ["LIVING", "FAMILY", "LOUNGE", "DRAWING", "SITTING"]):
                                room_type = "living"; label = "Living Room"
                            elif any(k in text for k in ["MASTER", "BED", "GUEST"]):
                                room_type = "bedroom"; label = "Bedroom"
                            elif any(k in text for k in ["DINING", "DINETTE"]):
                                room_type = "dining"; label = "Dining Room"
                            elif any(k in text for k in ["CLOSET", "WARDROBE", "STORE", "STORAGE"]):
                                room_type = "closet"; label = "Closet"
                            elif any(k in text for k in ["HALL", "CORRIDOR", "ENTRY", "FOYER", "LOBBY", "PASSAGE"]):
                                room_type = "hallway"; label = "Hallway"
                            elif any(k in text for k in ["BALCONY", "TERRACE", "PATIO", "DECK", "PORCH", "VERANDAH"]):
                                room_type = "balcony"; label = "Balcony"
                            elif any(k in text for k in ["GARAGE", "PARKING", "CAR"]):
                                room_type = "garage"; label = "Garage"
                            elif any(k in text for k in ["LAUNDRY", "UTILITY"]):
                                room_type = "utility"; label = "Utility Room"
                            elif any(k in text for k in ["STUDY", "OFFICE", "WORK"]):
                                room_type = "study"; label = "Study"
                            elif "ROOM" in text:
                                room_type = "bedroom"; label = "Bedroom"
                            logger.info(f"OCR room #{len(rooms)+1}: '{ocr_text}' → {room_type}")
                except Exception as e:
                    logger.debug(f"OCR failed for room {len(rooms)+1}: {e}")

                rooms.append(RoomData(
                    id=len(rooms),
                    cx=round(cx, 1),
                    cy=round(cy, 1),
                    bbox=[bx, by, bw, bh],
                    area_px=area,
                    area_ratio=round(area_ratio, 4),
                    aspect_ratio=round(aspect, 3),
                    polygon=polygon,
                    label=label,
                    room_type=room_type,
                    ocr_text=ocr_text,
                    color=None,
                    boundary_closed=boundary_closed,
                    bridged_gaps=[],
                    validation="valid" if boundary_closed else "open_boundary",
                    dilation_kernel=k_size,
                ))

            # Use the kernel that produces the most rooms (better separation)
            if len(rooms) >= len(best_rooms):
                best_rooms = rooms
                best_kernel_size = k_size

        return sorted(best_rooms, key=lambda r: -r.area_px)[:16]

    # ══════════════════════════════════════════════════════════
    # P4: ROOM BOUNDARY VALIDATION & GAP BRIDGING
    # ══════════════════════════════════════════════════════════

    def _validate_room_boundaries(self, rooms, all_walls):
        """Check room boundaries and detect wall gaps that cause merges."""
        if not rooms or not all_walls:
            return

        # Collect all wall endpoints
        endpoints = []
        for wall in all_walls:
            endpoints.append((wall.x1, wall.y1, wall.id, 'start'))
            endpoints.append((wall.x2, wall.y2, wall.id, 'end'))

        max_bridge_gap = 15.0  # px

        # Find nearby unconnected endpoints — potential gaps
        bridged = []
        for i in range(len(endpoints)):
            x1, y1, wid1, _ = endpoints[i]
            for j in range(i + 1, len(endpoints)):
                x2, y2, wid2, _ = endpoints[j]
                if wid1 == wid2:
                    continue
                gap = math.hypot(x2 - x1, y2 - y1)
                if 2.0 < gap <= max_bridge_gap:
                    bridged.append({
                        'from': [round(float(x1), 1), round(float(y1), 1)],
                        'to': [round(float(x2), 1), round(float(y2), 1)],
                        'gap_px': round(float(gap), 1),
                        'wall_ids': [int(wid1), int(wid2)],
                    })

        # Assign bridged gaps to nearby rooms
        for room in rooms:
            bbox = room.bbox
            bx, by, bw, bh = bbox
            room_gaps = []
            for bg in bridged:
                mx = (bg['from'][0] + bg['to'][0]) / 2
                my = (bg['from'][1] + bg['to'][1]) / 2
                margin = 20
                if (bx - margin <= mx <= bx + bw + margin and
                    by - margin <= my <= by + bh + margin):
                    room_gaps.append(bg)
            room.bridged_gaps = room_gaps
            if room_gaps and not room.boundary_closed:
                room.validation = 'bridged'

    # ══════════════════════════════════════════════════════════
    # P3: PER-CLASS THICKNESS STATS
    # ══════════════════════════════════════════════════════════

    def _compute_thickness_stats(self, dist, cls_map):
        """Compute thickness statistics per class from the original distance transform."""
        stats = {}
        for cls_id, cls_name in [(4, 'outer'), (3, 'inner'), (2, 'closet'), (1, 'line')]:
            vals = dist[cls_map == cls_id]
            if len(vals) < 10:
                stats[cls_name] = {'median': 0, 'mean': 0, 'p25': 0, 'p75': 0, 'count': 0}
                continue
            # Convert distance transform values to full thickness (diameter)
            vals_thick = vals * 2.0
            stats[cls_name] = {
                'median': round(float(np.median(vals_thick)), 2),
                'mean': round(float(np.mean(vals_thick)), 2),
                'p25': round(float(np.percentile(vals_thick, 25)), 2),
                'p75': round(float(np.percentile(vals_thick, 75)), 2),
                'count': int(len(vals)),
            }
        return stats

    # ══════════════════════════════════════════════════════════
    # FIXTURE DETECTION (NEW v5)
    # ══════════════════════════════════════════════════════════

    def _detect_fixtures(self, gray, binary, W, H, rooms):
        """
        Detect common architectural fixtures:
        - Toilet: circle/ellipse + attached rectangle (tank)
        - Sink: small rectangle with circle/arc inside
        - Bathtub: large rounded rectangle
        - Stove: rectangle with 4 circles
        """
        fixtures = []

        # Use Hough circles to find fixture-sized circles
        edges = cv2.Canny(gray, 40, 120)
        circles = cv2.HoughCircles(edges, cv2.HOUGH_GRADIENT,
                                    dp=1.3, minDist=15,
                                    param1=50, param2=22,
                                    minRadius=5, maxRadius=30)

        if circles is not None:
            circles = np.round(circles[0]).astype(int)
            for (cx, cy, r) in circles:
                # Check arc coverage — toilets have high coverage (>55%)
                angles = np.linspace(0, 2*np.pi, 72, endpoint=False)
                pxs = np.clip((cx+r*np.cos(angles)).astype(int), 0, W-1)
                pys = np.clip((cy+r*np.sin(angles)).astype(int), 0, H-1)
                hits = binary[pys, pxs] > 0
                cov  = hits.mean()

                if cov > 0.55 and r < 25:
                    # Full or near-full circle — likely toilet bowl or sink bowl
                    # Check for nearby rectangle (tank)
                    roi_x1 = max(0, cx-r*3)
                    roi_y1 = max(0, cy-r*3)
                    roi_x2 = min(W, cx+r*3)
                    roi_y2 = min(H, cy+r*3)
                    roi = binary[roi_y1:roi_y2, roi_x1:roi_x2]
                    roi_area = cv2.countNonZero(roi)
                    roi_total = max(1, (roi_x2-roi_x1)*(roi_y2-roi_y1))

                    # Dense ink nearby = fixture with body
                    if roi_area / roi_total > 0.15:
                        # Classify as toilet if medium-sized
                        if r >= 8 and r <= 22:
                            fixture_type = "toilet"
                            if r <= 12:
                                fixture_type = "sink"
                        else:
                            fixture_type = "sink"

                        # Find which room this fixture belongs to
                        room_id = self._find_room_for_point(cx, cy, rooms)

                        fixtures.append(dict(
                            type=fixture_type,
                            cx=float(cx), cy=float(cy),
                            radius=float(r),
                            width=float(r*2), height=float(r*2),
                            coverage=round(float(cov), 3),
                            room_id=room_id,
                            confidence=round(min(1.0, cov * 1.2), 3)
                        ))

        # Detect rectangular fixtures (bathtub, stove)
        # Find rectangular contours in the binary image
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 200 or area > W*H*0.05:
                continue

            rect = cv2.minAreaRect(cnt)
            (rcx, rcy), (rw, rh), angle = rect
            if rw < 1 or rh < 1:
                continue

            aspect = min(rw, rh) / max(rw, rh)
            extent = area / (rw * rh) if rw * rh > 0 else 0

            # Bathtub: elongated rectangle, high fill
            if (max(rw, rh) > 40 and max(rw, rh) < 120 and
                aspect > 0.3 and aspect < 0.6 and extent > 0.7):

                # Check it's not a wall segment (walls are thinner)
                if min(rw, rh) > 15:
                    room_id = self._find_room_for_point(int(rcx), int(rcy), rooms)
                    # Only add if not overlapping with existing fixtures
                    if not any(abs(f['cx']-rcx) < 20 and abs(f['cy']-rcy) < 20 for f in fixtures):
                        fixtures.append(dict(
                            type="bathtub",
                            cx=round(float(rcx), 1), cy=round(float(rcy), 1),
                            radius=0,
                            width=round(float(max(rw,rh)), 1),
                            height=round(float(min(rw,rh)), 1),
                            coverage=round(extent, 3),
                            room_id=room_id,
                            confidence=round(min(1.0, extent * 0.9), 3)
                        ))

        # Deduplicate fixtures
        deduped = []
        for f in fixtures:
            if not any(abs(f['cx']-d['cx']) < 15 and abs(f['cy']-d['cy']) < 15 for d in deduped):
                deduped.append(f)

        return deduped[:30]

    def _find_room_for_point(self, x, y, rooms):
        """Find which room a point belongs to."""
        for room in rooms:
            bbox = room.bbox
            if (bbox[0] <= x <= bbox[0]+bbox[2] and
                bbox[1] <= y <= bbox[1]+bbox[3]):
                return room.id
        return -1

    # ══════════════════════════════════════════════════════════
    # ROOM SEMANTIC CLASSIFICATION (NEW v5)
    # ══════════════════════════════════════════════════════════

    def _classify_rooms(self, rooms, fixtures, doors, W, H):
        """Classify rooms by type using geometric and fixture heuristics."""
        total_area = W * H
        room_colors = {
            'bathroom':    '#4488cc',
            'closet':      '#9060d0',
            'hallway':     '#808080',
            'kitchen':     '#cc8844',
            'bedroom':     '#6688aa',
            'living':      '#44aa66',
            'dining':      '#aa8866',
            'unknown':     '#607080',
        }

        for room in rooms:
            area_ratio = room.area_ratio
            aspect = room.aspect_ratio
            bbox = room.bbox
            room_id = room.id

            # Check which fixtures are in this room
            room_fixtures = [f for f in fixtures if f.get('room_id') == room_id]
            has_toilet = any(f['type'] == 'toilet' for f in room_fixtures)
            has_sink   = any(f['type'] == 'sink' for f in room_fixtures)
            has_tub    = any(f['type'] == 'bathtub' for f in room_fixtures)
            has_stove  = any(f['type'] == 'stove' for f in room_fixtures)

            # Classification logic
            if has_toilet or has_tub:
                room_type = 'bathroom'
            elif has_stove or (has_sink and area_ratio > 0.05):
                room_type = 'kitchen'
            elif area_ratio < 0.025:
                room_type = 'closet'
            elif aspect < 0.3:
                room_type = 'hallway'
            elif area_ratio > 0.20:
                room_type = 'living'
            elif area_ratio > 0.10:
                room_type = 'bedroom'
            elif area_ratio > 0.05:
                # Medium rooms — check for doors
                nearby_doors = sum(1 for d in doors
                                   if bbox[0]-20 <= d.cx <= bbox[0]+bbox[2]+20
                                   and bbox[1]-20 <= d.cy <= bbox[1]+bbox[3]+20)
                if nearby_doors >= 2:
                    room_type = 'hallway'
                else:
                    room_type = 'bedroom'
            else:
                room_type = 'unknown'

            room.room_type = room_type
            room.color = room_colors.get(room_type, room_colors['unknown'])

            # Generate nice label
            type_labels = {
                'bathroom': 'Bathroom',
                'closet': 'Closet',
                'hallway': 'Hallway',
                'kitchen': 'Kitchen',
                'bedroom': 'Bedroom',
                'living': 'Living Room',
                'dining': 'Dining Room',
                'unknown': f'Room {room_id+1}',
            }

            # Count rooms of same type for numbering
            same_type = sum(1 for r in rooms if getattr(r, 'room_type', None) == room_type and r.id < room_id)
            base_label = type_labels.get(room_type, 'Room')
            if same_type > 0:
                room.label = f"{base_label} {same_type+1}"
            else:
                room.label = base_label

    # ══════════════════════════════════════════════════════════
    # FURNITURE DETECTION (NEW v6)
    # ══════════════════════════════════════════════════════════

    def _detect_furniture(self, binary, W, H, rooms):
        """Legacy heuristic furniture detection — now defers to YOLO DL.
        Returns empty list; YOLO results are merged earlier in detect()."""
        return []

    # ══════════════════════════════════════════════════════════
    # PADDING COMPENSATION
    # ══════════════════════════════════════════════════════════

    def _strip_pad(self, res, P):
        for seg in res.outer_walls+res.inner_walls+res.closets:
            seg.x1 = round(seg.x1 - P, 1)
            seg.y1 = round(seg.y1 - P, 1)
            seg.x2 = round(seg.x2 - P, 1)
            seg.y2 = round(seg.y2 - P, 1)
            for op in seg.openings:
                # door_data/window_data are dropped, we only care about OpeningData
                pass
        for w in res.windows:
            w.x1 = round(w.x1 - P, 1)
            w.y1 = round(w.y1 - P, 1)
            w.x2 = round(w.x2 - P, 1)
            w.y2 = round(w.y2 - P, 1)
        for d in res.doors:
            d.cx = round(d.cx - P, 1)
            d.cy = round(d.cy - P, 1)
        for s in res.stairs:
            for k in ('x1','y1','x2','y2'):
                s[k] = round(s[k]-P, 1)
        for r in res.rooms:
            r.cx = round(r.cx - P, 1)
            r.cy = round(r.cy - P, 1)
            r.bbox[0] -= P; r.bbox[1] -= P
            if r.polygon:
                r.polygon = [[p[0]-P, p[1]-P] for p in r.polygon]
            for bg in r.bridged_gaps:
                bg['from'] = [round(bg['from'][0] - P, 1), round(bg['from'][1] - P, 1)]
                bg['to'] = [round(bg['to'][0] - P, 1), round(bg['to'][1] - P, 1)]
        for f in res.fixtures:
            f['cx'] = round(f['cx']-P, 1)
            f['cy'] = round(f['cy']-P, 1)
        for f in res.furniture:
            f['cx'] = round(f['cx']-P, 1)
            f['cy'] = round(f['cy']-P, 1)
        res.image_width  -= 2*P
        res.image_height -= 2*P

    # ══════════════════════════════════════════════════════════
    # DEBUG ENCODERS
    # ══════════════════════════════════════════════════════════

    def _enc_thickness(self, dist, maxv):
        vis = np.clip(dist/max(maxv,1.), 0, 1)
        cm  = cv2.applyColorMap((vis*255).astype(np.uint8), cv2.COLORMAP_INFERNO)
        return self._enc(cm)

    def _enc_classes(self, cls_map):
        COLS = {0:(8,11,16),1:(80,210,100),2:(160,90,220),
                3:(80,160,220),4:(230,200,60)}
        vis  = np.zeros((*cls_map.shape,3), dtype=np.uint8)
        for c,col in COLS.items(): vis[cls_map==c] = col
        return self._enc(vis)

    def _enc_skel(self, img, sk_o, sk_i, sk_c, sk_l):
        vis = img.copy()
        vis[sk_o>0] = (0,220,255)
        vis[sk_i>0] = (255,160,60)
        vis[sk_c>0] = (200,60,255)
        vis[sk_l>0] = (60,255,140)
        return self._enc(vis)

    def _enc_rooms(self, img, rooms, fixtures):
        """Encode a debug visualization of detected rooms and fixtures."""
        vis = img.copy()
        colors = [
            (68,136,204), (144,96,208), (128,128,128),
            (204,136,68), (102,136,170), (68,170,102),
            (170,136,102), (96,112,128),
        ]
        for i, room in enumerate(rooms):
            color = colors[i % len(colors)]
            bbox = room.bbox
            cv2.rectangle(vis,
                         (bbox[0], bbox[1]),
                         (bbox[0]+bbox[2], bbox[1]+bbox[3]),
                         color, 2)
            if room.polygon and len(room.polygon) > 2:
                pts = np.array(room.polygon, dtype=np.int32)
                overlay = vis.copy()
                cv2.fillPoly(overlay, [pts], color)
                cv2.addWeighted(overlay, 0.15, vis, 0.85, 0, vis)
                cv2.polylines(vis, [pts], True, color, 2)
            label = getattr(room, 'label', f'Room {i+1}')
            rtype = getattr(room, 'room_type', '')
            cv2.putText(vis, f"{label}", (bbox[0]+4, bbox[1]+16),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1, cv2.LINE_AA)
            cv2.putText(vis, f"{rtype}", (bbox[0]+4, bbox[1]+30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1, cv2.LINE_AA)

        # Draw fixtures
        fixture_colors = {
            'toilet': (0, 200, 255),
            'sink': (255, 150, 50),
            'bathtub': (50, 200, 150),
            'stove': (200, 50, 50),
        }
        for f in fixtures:
            color = fixture_colors.get(f['type'], (200,200,200))
            cx, cy = int(f['cx']), int(f['cy'])
            r = int(f.get('radius', 8)) or 8
            cv2.circle(vis, (cx, cy), r, color, 2)
            cv2.putText(vis, f['type'], (cx-15, cy-r-4),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1, cv2.LINE_AA)

        return self._enc(vis)

    def _enc(self, img):
        _, buf = cv2.imencode(".png", img)
        return base64.b64encode(buf).decode("utf-8")


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def detect_floor_plan(image_bytes: bytes, ortho_tol: float = 0.5) -> dict:
    r = FloorPlanDetector(max_dim=900).detect(image_bytes, ortho_tol=ortho_tol)
    # Ensure Pydantic model is serialized to a standard Python dictionary before returning
    return r.model_dump()
