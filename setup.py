"""
setup.py — One-command setup for Provenance.

Usage:  python3 setup.py
        python3 setup.py /path/to/Music Library.xml   # if auto-detect fails

What it does:
  1. Finds your iTunes / Music library XML automatically
  2. Parses it into a local database (~10 seconds)
  3. Builds the 3D graph
  4. Opens Provenance in your browser at http://localhost:8765
  5. Starts background enrichment (band memberships, credits, studios)
     — the graph fills in over the next few hours while you explore

No pip installs required — pure Python stdlib.
"""
import subprocess, sys, os
from pathlib import Path

ROOT = Path(__file__).parent

# ── 1. Find iTunes Library XML ────────────────────────────────────────────────
CANDIDATE_PATHS = [
    Path.home() / "Music/Music/Music Library.xml",
    Path.home() / "Music/iTunes/iTunes Music Library.xml",
    Path.home() / "Music/iTunes/iTunes Library.xml",
]

def find_xml(override=None):
    if override:
        p = Path(override).expanduser()
        if p.exists():
            return p
        sys.exit(f"✗ File not found: {p}")
    for p in CANDIDATE_PATHS:
        if p.exists():
            return p
    print("✗ Could not find your Music library XML automatically.")
    print("  In Music.app: File → Library → Export Library…  then re-run:")
    print("  python3 setup.py /path/to/exported/Library.xml")
    sys.exit(1)

def run(cmd, desc):
    print(f"\n→ {desc}")
    result = subprocess.run([sys.executable] + cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"✗ Failed: {' '.join(cmd)}")

# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    xml = find_xml(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"\nProvenance setup")
    print(f"{'─' * 40}")
    print(f"Library: {xml}")

    run(["ingest/parse_itunes.py",       str(xml)], "Parsing your library…")
    run(["ingest/import_enrichment.py"],           "Importing enrichment corpus…")
    run(["graph/build_graph.py"],                  "Building graph…")

    print("\n✓ Done — opening Provenance")
    print("  Deeper connections (producers, engineers, studios) are enriching")
    print("  in the background — the graph will fill in over the next few hours.\n")

    subprocess.Popen([sys.executable, "api/server.py"])
    subprocess.Popen([sys.executable, "ingest/enrich_all.py"], cwd=ROOT)
