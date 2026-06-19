@echo off
title FloorPlan3D v6 — Production Architectural Visualization
color 0A
echo.
echo  =====================================================
echo   FloorPlan3D v6 — Production Architectural Tool
echo  =====================================================
echo   Features: 3D Viewer, Walk Mode, Voice Commands,
echo   Command Bar, BOM, Compliance, Multi-Format Export
echo  =====================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install from python.org
    pause
    exit
)

:: Install dependencies
echo  [1/3] Installing Python dependencies...
pip install flask flask-cors opencv-python-headless numpy pymupdf pytesseract ifcopenshell --quiet
if errorlevel 1 (
    echo  [ERROR] pip install failed. Try: pip install -r backend/requirements.txt
    pause
    exit
)

echo  [2/3] Starting OpenCV backend server...
echo.
cd backend

:: Open browser after 2 seconds
start "" /B cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5050"

echo  [3/3] Server running at http://localhost:5050
echo.
echo  === Quick Start ===
echo  - Click [Demo] to load a sample floor plan
echo  - Press Ctrl+K for the command bar
echo  - Press V for voice commands
echo  - Press ? for keyboard shortcuts
echo  - Upload your own floor plan (PNG/JPG)
echo.
echo  Press CTRL+C to stop the server.
echo.
python server.py
pause
