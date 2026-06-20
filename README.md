# Floor Plan — Intelligent Architecture Engine

Converts 2D architectural floor plans into top-notch, interactive 3D BIM models. 
Uses **OpenCV** for advanced semantic heuristic analysis and **Three.js** to procedurally generate industry-standard 3D architectural representations directly in the browser.

---

## 🚀 Quick Start

### Windows
```
Double-click  START_WINDOWS.bat
```

### Mac / Linux
```bash
chmod +x start_mac_linux.sh
./start_mac_linux.sh
```

### Manual
```bash
pip install flask flask-cors opencv-python-headless numpy pymupdf easyocr

cd backend
python server.py
# Open frontend/index.html in your browser
# or visit http://localhost:5050
```

---

## 🛠️ Intelligent Detection Pipeline & Features
This engine combines high-speed OpenCV heuristics for structural tracking with lightweight Deep Learning (YOLO & EasyOCR) for furniture classification and text recognition.

### 1. Geometric Structural Analysis & Drawing
Every ink stroke is measured using an **L2 distance transform** to dynamically determine architectural features. 
- **Orthogonal Forcing:** Wall segments mapped within ±4 degrees of alignment are mathematically forced to perfectly orthogonal 0° or 90° lines, significantly improving 2D-to-3D visual stability.
- **Corner Snapping:** Post-process grouping sweeps for detached corners and perfectly fuses L-junctions and T-junctions within a 15px radius for airtight modeling.
- **CAD-like Polyline Wall Tool:** Click-to-chain walls in the editor with 90-degree orthogonal constraint (Hold Shift), vertex snapping (within 0.5m of corners), and a live green preview. Right-click to cancel the chain.
- **Dynamic Resolution Morphing:** Architectural erosions and dilations automatically scale relative to the input image footprint (`W * H`), making the detector scale-agnostic.

### 2. AI Room & Text Recognition (OCR)
- **EasyOCR Integration:** Replaced legacy Tesseract with an automated EasyOCR pipeline that runs on first detection. It reads text labels inside room boundaries (e.g. "Kitchen", "Master Bedroom", "Bath") to categorize room types.
- **Default Material Texturing:** Assigns floor textures and materials (like wood floors for bedrooms, tiles for bathrooms) based on identified room categories.

### 3. First-Person Physics Walkthrough
- **Collision Detection:** Walk mode (`🚶 Walk`) features real physics using Three.js raycasting to detect walls and doors so users cannot walk through structural boundaries.
- **Wall Sliding:** Movement handles glancing collisions gracefully by sliding along the X or Z axis rather than stopping completely.

### 4. Scale Calibration Tool
- **Real-world Scaling:** Use the **📐 Calibrate** tool to select a wall, input its real-world length in meters, and automatically rescale the entire 3D model footprint to real dimensions.

### 5. Industry Standard BIM 3D Splitting
Rather than overlapping solid meshes, doors and windows interact natively with the topological spaces:
- **Geometry Splitting**: The Javascript engine calculates intersection projections and completely removes sections of bounding walls when doors or windows span across them, opening functional architectural holes.
- **Sill & Lintel Creation**: Windows accurately construct a lower sill support mesh, and an upper header lintel mesh.
- **Rotation Inheritance**: Open doors natively inherit the angular rotation of their parent wall, achieving a 100% proper layout match aligned with strict architectural standards.

### 6. Interior Design Recognition
The engine automatically deduces layout features by analyzing objects natively bound inside room zones:
- Large blocks in **Bedrooms** → **3D Beds** 
- Elongated, dense blocks in **Living Rooms** → **Sofas & Couches**
- Broad geometric footprints in **Dining & Kitchen** → **Dining Tables & Islands**
- Floating masses in **Hallways** → **Rugs**

### 7. Custom Styling & Aesthetics
Using the **Selection Tool** (`3`), any structural or interior element (walls, furniture, doors) can be individually selected. A context-aware **Color Selection Picker** surfaces in the floating bottom toolbar that allows you to directly manipulate and paint the specific object's 3D Material—acting as a true interactive design tool overlay on your floor plan!

### 8. True BIM & Interoperability
- **PDF Vector Ingestion**: The backend utilizes `PyMuPDF` to intelligently intercept PDF uploads. It renders architectural vector linework at extremely high DPI bounds, bypassing standard OpenCV pixel-noise issues on digital prints.
- **Physical Glazing Shaders**: Utilizing `THREE.MeshPhysicalMaterial` with true Index of Refraction properties (`ior: 1.5`), windowpanes bend and obscure environmental layouts realistically.
- **Structural Cavity Slicing**: Try slicing the exterior bounding walls with the Section Cut tool! Outer walls are automatically procedurally generated with two tiers: a smaller solid darker internal structural core element nestled perfectly inside the drywall mesh.

### 9. Multi-User Collaboration & Export
- **Step-serialization Export**: A native 100% pure JS `ISO-10303-21` generator converts the topological mappings into raw `.ifc` `IfcWallStandardCase` schema headers natively. Click **EXPORT IFC** out of the UI to easily import raw AI mapping into ArchiCAD.
- **PeerJS Distributed Multiplayer**: Click the **👥 Collab** button on the Navbar to construct a P2P WebRTC data connection directly inside your cache! Hosting a session and sending the ID to a colleague establishes a direct link replicating `Added Walls` and material `Color Updates` perfectly in-sync.

---

## 📂 Project Structure

```
floorplan/
├── backend/
│   ├── detector.py        ← High-accuracy 2D-to-3D OpenCV detection engine
│   ├── server.py          ← Python Flask server (with PyMuPDF hooks)
│   └── requirements.txt
├── frontend/
│   ├── index.html         ← Three.js Viewer, Floating Glass UI 
│   └── bim_collab.js      ← IFC schema generator and WebRTC PeerJS sync
├── START_WINDOWS.bat      ← Windows one-click launcher
├── start_mac_linux.sh     ← Mac/Linux launcher
└── README.md
```

---

## 🛠️ API Interface Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Application status |
| POST | `/analyze` | Analyze uploaded floor plan image |
| GET | `/demo` | Generate synthetic demo plan |

### POST /analyze Payload Return Format
```json
{
  "image_width": 720,
  "image_height": 580,
  "outer_walls": [{"x1":50,"y1":50,"x2":670,"y2":50,"thickness_px":14.2}],
  "inner_walls": [...],
  "windows": [{"x1":130,"y1":50,"x2":240,"y2":50,"orient":"h","gap_px":4.0}],
  "doors": [{"cx":360,"cy":290,"radius_px":48,"coverage":0.27}],
  "rooms": [{"id":0,"room_type":"living","area_px":12400}],
  "furniture": [{"type":"sofa","cx":400,"cy":250,"width":80,"height":40,"angle":0}],
  "summary": {"outer_walls":4,"inner_walls":5,"windows":8,"doors":4,"furniture":2}
}
```

---

## 🎨 User Interface Options

In the beautifully redesigned Light Mode Workspace, tweak real-time architectural properties:

| Settings | Range | Description |
|-----------|-------|-------------|
| Wall Height | 1.8–6.0 m | Total height of extruded geometry |
| Door Height | 1.6–3.5 m | Adjusts the cutout mesh headers |
| Window Sill | 0.2–1.5 m | Floor-to-window cutoff geometry |
| Wireframe | Toggle | Analyze mesh topological intersections |
| Interior Lights | Toggle | Dynamic ThreeJS point spotlights |
| Show Ceilings & Roofs | Toggle | Auto-generate flat ceiling meshes over closed room boundaries |
| Developer Mode | Toggle | Unhide low-level OpenCV pipeline stages and debug panels |

---

## 📸 Tips for Best Results

- **Standardization**: High-contrast, standard architectural drafted maps work best.
- **Resolution Agnostic**: Dynamic morphological kernels support anything from 500x500 sketches to 4K industry blueprints.
- Use the **Thickness Multiplier** slider if walls are rendering excessively wide.
- Use **Debug Vision** in the sidebar to visualize exactly how the CV heuristics assign Semantic colors!
