#!/bin/bash
# FloorPlan3D — Mac/Linux Startup Script

echo ""
echo "====================================================="
echo "  FloorPlan3D — Rule-Based Geometric Detection"
echo "====================================================="
echo ""

# Check python3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 not found. Install from python.org"
    exit 1
fi

# Install deps
echo "[1/3] Installing Python dependencies..."
pip3 install flask flask-cors opencv-python-headless numpy --quiet

echo "[2/3] Starting OpenCV backend server..."

# Open browser after 2 seconds
(sleep 2 && open "http://localhost:5050" 2>/dev/null || xdg-open "http://localhost:5050" 2>/dev/null) &

cd "$(dirname "$0")/backend"
echo "[3/3] Server running at http://localhost:5050"
echo ""
echo " The frontend will open in your browser."
echo " Press CTRL+C to stop."
echo ""
python3 server.py
