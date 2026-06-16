"""
bundle.py — Produces a single self-contained bundle.html.
Inlines graph data + CDN scripts so the file works offline with no server.

Usage: python3 scripts/bundle.py
Output: web/bundle.html
"""
import json, re, urllib.request
from pathlib import Path

ROOT      = Path(__file__).parent.parent
HTML_FILE = ROOT / "web" / "index.html"
JSON_FILE = ROOT / "data" / "graph.json"
CACHE_DIR = ROOT / "scripts" / ".cdn_cache"
OUT_FILE  = ROOT / "web" / "bundle.html"

CDN_SCRIPTS = [
    ("three.min.js",          "https://unpkg.com/three@0.158.0/build/three.min.js"),
    ("3d-force-graph.min.js", "https://unpkg.com/3d-force-graph@1.73.0/dist/3d-force-graph.min.js"),
]

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Download CDN scripts once, cache locally
cdn_js = {}
for filename, url in CDN_SCRIPTS:
    cache_path = CACHE_DIR / filename
    if not cache_path.exists():
        print(f"Downloading {filename} …")
        urllib.request.urlretrieve(url, cache_path)
    else:
        print(f"Using cached {filename}")
    cdn_js[url] = cache_path.read_text()

print("Reading graph.json …")
graph = json.loads(JSON_FILE.read_text())

print("Reading index.html …")
html = HTML_FILE.read_text()

# Replace each CDN <script src="…"> with an inline <script>…</script>
for url, js in cdn_js.items():
    html = html.replace(
        f'<script src="{url}"></script>',
        f'<script>{js}</script>',
    )

# Replace fetch('/graph.json') block with inline data reference
html = re.sub(
    r"const res = await fetch\('/graph\.json'\);\s*graphData = await res\.json\(\);",
    "graphData = window.__GRAPH_DATA__;",
    html,
)

# Mark as bundle so play button is suppressed
html = html.replace("const IS_BUNDLE = false;", "const IS_BUNDLE = true;", 1)

# Inject graph data at the top of <head> — must be defined before init() runs
data_tag = f'<script>window.__GRAPH_DATA__ = {json.dumps(graph, separators=(",", ":"))}</script>\n'
html = html.replace("<head>", "<head>\n" + data_tag, 1)

OUT_FILE.write_text(html)
size_mb = OUT_FILE.stat().st_size / 1_048_576
print(f"Done → {OUT_FILE}  ({size_mb:.1f} MB)")
