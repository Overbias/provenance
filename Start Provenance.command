#!/bin/bash
# Double-click this file to start Provenance.
# It will open automatically in your browser at http://localhost:8765

# Find the folder this script lives in (works regardless of where it's cloned)
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Starting Provenance..."
echo ""

# Check if already running on port 8765
if lsof -ti:8765 >/dev/null 2>&1; then
    echo "Provenance is already running — opening in browser."
    open http://localhost:8765
    exit 0
fi

# Check that the graph has been built
if [ ! -f "$DIR/data/graph.json" ]; then
    echo "Graph not found. Running setup first (this may take a minute)..."
    python3 "$DIR/setup.py"
else
    python3 "$DIR/api/server.py"
fi
