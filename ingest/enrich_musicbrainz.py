"""
enrich_musicbrainz.py — MusicBrainz enrichment: release IDs, artist IDs, band memberships.

Three phases (each resumable — safe to interrupt and restart):

  Phase 1 — Match albums to MB release IDs
    1a. Albums with discogs_id: URL relationship lookup (very reliable)
    1b. Albums without: artist+title text search (threshold-filtered)

  Phase 2 — Extract primary artist MBIDs from each matched release

  Phase 3 — For each artist with MBID, fetch band membership relationships
             → stored in artist_relationships table

New graph edges this enables:
  artist ←[member of band]→ band ←[member of band]→ artist

Run:   python3 ingest/enrich_musicbrainz.py
Safe:  fully resumable; skips already-matched rows each phase.
Time:  ~2–3 hrs (MB rate limit: 1 req/s; ~6,000 total requests).
"""
import sqlite3, requests, time, re
from pathlib import Path
from difflib import SequenceMatcher

DB      = Path(__file__).parent.parent / "data" / "library.db"
BASE    = "https://musicbrainz.org/ws/2"
HEADERS = {"User-Agent": "MusicGraphPersonal/1.0 ( bengeorgiades@me.com )"}
DELAY   = 1.1   # MB policy: ≤ 1 req/s

def get(path, params=None, _retries=5):
    params = {**(params or {}), "fmt": "json"}
    for attempt in range(_retries):
        r = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=15)
        if r.status_code == 503:
            wait = 2 ** attempt * 2   # 2, 4, 8, 16, 32 s
            print(f"  503 rate-limited — waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(DELAY)
        return r.json()
    raise Exception(f"Failed after {_retries} retries: {BASE}{path}")

def sim(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# ── schema migration ──────────────────────────────────────────────────────────
def migrate(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS artist_relationships (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            artist_id     INTEGER REFERENCES artists(id),
            related_name  TEXT,
            related_mb_id TEXT,
            relation_type TEXT,
            direction     TEXT,
            begin_year    INTEGER,
            end_year      INTEGER,
            ended         INTEGER DEFAULT 0,
            UNIQUE(artist_id, related_mb_id, relation_type)
        );
    """)
    con.commit()

# ── Phase 1a: Discogs ID → MB release ID ─────────────────────────────────────
def mb_from_discogs(discogs_id):
    """URL relationship lookup — MusicBrainz links directly to Discogs release URLs."""
    try:
        data = get("/url", {
            "resource": f"https://www.discogs.com/release/{discogs_id}",
            "inc": "release-rels",
        })
        for rel in data.get("relations", []):
            if rel.get("target-type") == "release":
                return rel["release"]["id"]
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None   # MB has no link for this Discogs release
        raise
    except Exception:
        pass
    return None

# ── Phase 1b: text search fallback ───────────────────────────────────────────
_ALL_PARENS = re.compile(r'\s*[\(\[].*?[\)\]]')

def core_title(title):
    return _ALL_PARENS.sub('', title).strip() or title

def mb_from_search(artist, title):
    """Artist+title search — only accepts matches scoring ≥ 0.75."""
    for t in dict.fromkeys([title, core_title(title)]):   # deduplicated
        try:
            data = get("/release", {
                "query": f'artist:"{artist}" release:"{t}"',
                "limit": 5,
            })
            for r in data.get("releases", []):
                credits = r.get("artist-credit", [])
                ra = " ".join(
                    c["artist"]["name"] for c in credits
                    if isinstance(c, dict) and "artist" in c
                )
                score = sim(r.get("title", ""), t) * 0.6 + sim(ra, artist) * 0.4
                if score >= 0.75:
                    return r["id"]
        except Exception:
            pass
    return None

def phase1(con):
    cur = con.cursor()

    # 1a — albums with discogs_id
    todo = cur.execute("""
        SELECT id, discogs_id FROM albums
        WHERE discogs_id IS NOT NULL AND mb_release_id IS NULL
    """).fetchall()
    print(f"\nPhase 1a — Discogs→MB lookup: {len(todo)} albums")

    ok = fail = 0
    for i, (aid, did) in enumerate(todo, 1):
        mbid = mb_from_discogs(did)
        if mbid:
            cur.execute("UPDATE albums SET mb_release_id=? WHERE id=?", (mbid, aid))
            con.commit()
            ok += 1
        else:
            fail += 1
        if i % 100 == 0:
            print(f"  [{i}/{len(todo)}] matched {ok}  not found {fail}")
    print(f"  Done — matched {ok}  not found {fail}")

    # 1b — albums without discogs_id
    todo2 = cur.execute("""
        SELECT id, artist, title FROM albums
        WHERE discogs_id IS NULL AND mb_release_id IS NULL
        AND artist != '' AND title != ''
    """).fetchall()
    print(f"\nPhase 1b — text search: {len(todo2)} albums")

    ok2 = fail2 = 0
    for i, (aid, artist, title) in enumerate(todo2, 1):
        mbid = mb_from_search(artist, title)
        if mbid:
            cur.execute("UPDATE albums SET mb_release_id=? WHERE id=?", (mbid, aid))
            con.commit()
            ok2 += 1
        else:
            fail2 += 1
        if i % 100 == 0:
            print(f"  [{i}/{len(todo2)}] matched {ok2}  not found {fail2}")
    print(f"  Done — matched {ok2}  not found {fail2}")

# ── Phase 2: artist MBIDs from releases ──────────────────────────────────────
def phase2(con):
    cur = con.cursor()
    todo = cur.execute("""
        SELECT id, mb_release_id FROM albums WHERE mb_release_id IS NOT NULL
    """).fetchall()
    print(f"\nPhase 2 — extracting artist MBIDs from {len(todo)} releases")

    updated = 0
    for i, (aid, mbid) in enumerate(todo, 1):
        try:
            data = get(f"/release/{mbid}", {"inc": "artist-credits"})
        except Exception as e:
            print(f"  error fetching release {mbid}: {e}")
            continue

        for credit in data.get("artist-credit", []):
            if not isinstance(credit, dict):
                continue
            a    = credit.get("artist", {})
            name = a.get("name", "").strip()
            mb_a = a.get("id")
            if not name or not mb_a:
                continue
            rows = cur.execute("""
                UPDATE artists SET mb_artist_id=?
                WHERE name=? AND mb_artist_id IS NULL
            """, (mb_a, name)).rowcount
            updated += rows

        if i % 100 == 0:
            con.commit()
            print(f"  [{i}/{len(todo)}] {updated} artist MBIDs set so far")

    con.commit()
    total = cur.execute(
        "SELECT COUNT(*) FROM artists WHERE mb_artist_id IS NOT NULL"
    ).fetchone()[0]
    print(f"  Done — artists with MB ID: {total}")

# ── Phase 3: band membership relationships ────────────────────────────────────
MEMBER_TYPES = {"member of band", "founding member of", "member of group"}

def phase3(con):
    cur = con.cursor()
    todo = cur.execute("""
        SELECT a.id, a.name, a.mb_artist_id FROM artists a
        WHERE a.mb_artist_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM artist_relationships ar WHERE ar.artist_id = a.id
        )
    """).fetchall()
    print(f"\nPhase 3 — band memberships for {len(todo)} artists")

    total = 0
    for i, (aid, name, mbid) in enumerate(todo, 1):
        try:
            data = get(f"/artist/{mbid}", {"inc": "artist-rels"})
        except Exception as e:
            print(f"  error fetching artist {mbid} ({name}): {e}")
            continue

        for rel in data.get("relations", []):
            if rel.get("type", "").lower() not in MEMBER_TYPES:
                continue
            target = rel.get("artist", {})
            rname  = target.get("name", "").strip()
            rmbid  = target.get("id")
            if not rname or not rmbid:
                continue

            begin  = rel.get("begin") or ""
            end    = rel.get("end") or ""
            cur.execute("""
                INSERT OR IGNORE INTO artist_relationships
                  (artist_id, related_name, related_mb_id, relation_type,
                   direction, begin_year, end_year, ended)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                aid, rname, rmbid, rel.get("type"),
                rel.get("direction"),
                int(begin[:4]) if begin else None,
                int(end[:4])   if end   else None,
                1 if rel.get("ended") else 0,
            ))
            total += 1

        if i % 50 == 0:
            con.commit()
            print(f"  [{i}/{len(todo)}] {total} relationships stored")

    con.commit()
    print(f"  Done — {total} band membership relationships")

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    con = sqlite3.connect(DB, timeout=30)
    migrate(con)

    have_mb = con.execute(
        "SELECT COUNT(*) FROM albums WHERE mb_release_id IS NOT NULL"
    ).fetchone()[0]
    print(f"Starting state: {have_mb} albums already have MB release IDs")

    phase1(con)
    phase2(con)
    phase3(con)

    print("\n── Final summary ──────────────────────────────────────────────────")
    print(f"Albums with MB release ID : {con.execute('SELECT COUNT(*) FROM albums WHERE mb_release_id IS NOT NULL').fetchone()[0]}")
    print(f"Artists with MB artist ID : {con.execute('SELECT COUNT(*) FROM artists WHERE mb_artist_id IS NOT NULL').fetchone()[0]}")
    print(f"Band membership relations : {con.execute('SELECT COUNT(*) FROM artist_relationships').fetchone()[0]}")
    con.close()

if __name__ == "__main__":
    main()
