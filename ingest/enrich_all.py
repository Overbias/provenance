"""
enrich_all.py — Background enrichment coordinator.

Runs automatically after setup.py. Do not run manually.

Sequence:
  1. MusicBrainz  (~2–3 hrs, free, no account needed)   → rebuild graph
  2. Discogs      (~2 hrs, needs DISCOGS_TOKEN in .env)  → rebuild graph

The graph rebuilds after each stage so the constellation fills in
gradually while the user is exploring. Each script is resumable —
safe to interrupt and restart.
"""
import subprocess, sys, os, sqlite3
from pathlib import Path

ROOT    = Path(__file__).parent.parent
DB      = ROOT / "data" / "library.db"
ENV     = ROOT / ".env"


def run(script, desc):
    print(f"\n[enrichment] {desc}")
    result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT)
    if result.returncode != 0:
        print(f"[enrichment] ✗ {script} failed — skipping")
        return False
    return True


def rebuild():
    print("[enrichment] Rebuilding graph…")
    subprocess.run([sys.executable, str(ROOT / "graph" / "build_graph.py")], cwd=ROOT)


def already_done(table, min_rows=10):
    try:
        con = sqlite3.connect(DB)
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        con.close()
        return count >= min_rows
    except Exception:
        return False


def discogs_token():
    token = os.environ.get("DISCOGS_TOKEN")
    if token:
        return token
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if line.startswith("DISCOGS_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


if __name__ == "__main__":
    print("\n[enrichment] Starting background enrichment — your graph will get richer over the next few hours.")
    print("[enrichment] You can explore Provenance now; it will update automatically.\n")

    # ── MusicBrainz ────────────────────────────────────────────────────────────
    if already_done("artist_relationships"):
        print("[enrichment] MusicBrainz already complete — skipping")
    else:
        if run("ingest/enrich_musicbrainz.py", "MusicBrainz band memberships (~2–3 hrs)…"):
            rebuild()

    # ── Discogs ────────────────────────────────────────────────────────────────
    token = discogs_token()
    if not token:
        print("\n[enrichment] Discogs token not found — skipping producer/engineer/studio enrichment.")
        print("[enrichment] To enable it:")
        print("[enrichment]   1. Create a free account at https://www.discogs.com")
        print("[enrichment]   2. Go to Settings → Developers → Generate token")
        print("[enrichment]   3. Add this line to .env in the provenance folder:")
        print("[enrichment]        DISCOGS_TOKEN=your_token_here")
        print("[enrichment]   4. Re-run: python3 ingest/enrich_all.py")
    elif already_done("credits"):
        print("[enrichment] Discogs already complete — skipping")
    else:
        if run("ingest/enrich_discogs.py", "Discogs credits, studios, labels (~2 hrs)…"):
            rebuild()

    print("\n[enrichment] All enrichment complete.")
