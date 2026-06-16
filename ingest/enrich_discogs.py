"""
enrich_discogs.py — Enrich library albums with Discogs credits.
Run: python3 enrich_discogs.py

Processes albums in play-count order (most-loved first).
Resumable: skips albums already marked enriched=1.
Rate: 60 req/min with token → ~2 hrs for full library.
"""
import sqlite3, requests, time, re, os, sys
from pathlib import Path
from difflib import SequenceMatcher

DB    = Path(__file__).parent.parent / "data" / "library.db"
TOKEN = os.environ.get("DISCOGS_TOKEN") or open(
    Path(__file__).parent.parent / ".env").read().split("=",1)[1].strip()

HEADERS = {
    "User-Agent": "MusicGraphPersonal/1.0",
    "Authorization": f"Discogs token={TOKEN}",
}
BASE = "https://api.discogs.com"
DELAY = 1.1   # seconds between calls — stays under 60/min

# ── role categorisation ───────────────────────────────────────────────────────
ROLE_MAP = [
    (re.compile(r"produc",      re.I), "producer"),
    (re.compile(r"engineer|recording|tracked", re.I), "engineer"),
    (re.compile(r"mix",         re.I), "engineer"),
    (re.compile(r"master",      re.I), "engineer"),
    (re.compile(r"written|compos|lyric|music by", re.I), "writer"),
    (re.compile(r"vocals?|singer|lead|backing", re.I), "musician"),
    (re.compile(r"guitar|bass|drum|piano|keys|organ|synth|"
                r"trumpet|sax|violin|cello|horn|percuss|"
                r"strings?|brass|woodwind|flute|harp|"
                r"turntabl|dj |sampl|program",
                re.I), "musician"),
    (re.compile(r"performer|instrument|plays", re.I), "musician"),
    (re.compile(r"arrang",      re.I), "arranger"),
]

STUDIO_ENTITY_TYPES = {
    "Recorded At", "Mixed At", "Mastered At",
    "Recorded At Studio", "Mixed At Studio",
}


def categorise(role):
    for pat, cat in ROLE_MAP:
        if pat.search(role):
            return cat
    return "other"


# ── database setup ────────────────────────────────────────────────────────────
SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS credits (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id     INTEGER REFERENCES albums(id),
    person_name  TEXT,
    role         TEXT,
    role_category TEXT,
    tracks       TEXT,
    discogs_artist_id INTEGER,
    UNIQUE(album_id, person_name, role)
);

CREATE TABLE IF NOT EXISTS studios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE,
    discogs_id  INTEGER
);

CREATE TABLE IF NOT EXISTS album_studios (
    album_id    INTEGER REFERENCES albums(id),
    studio_id   INTEGER REFERENCES studios(id),
    role        TEXT,
    PRIMARY KEY (album_id, studio_id, role)
);

CREATE TABLE IF NOT EXISTS labels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE,
    discogs_id  INTEGER
);

CREATE TABLE IF NOT EXISTS album_labels (
    album_id    INTEGER REFERENCES albums(id),
    label_id    INTEGER REFERENCES labels(id),
    catalog_number TEXT,
    PRIMARY KEY (album_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_credits_person ON credits(person_name);
CREATE INDEX IF NOT EXISTS idx_credits_cat    ON credits(role_category);
CREATE INDEX IF NOT EXISTS idx_credits_album  ON credits(album_id);
"""


def sim(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ── API calls ─────────────────────────────────────────────────────────────────
def search(artist, title):
    params = {"artist": artist, "release_title": title,
              "type": "release", "per_page": 10}
    r = requests.get(f"{BASE}/database/search", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json().get("results", [])


def get_release(rid):
    r = requests.get(f"{BASE}/releases/{rid}", headers=HEADERS)
    r.raise_for_status()
    return r.json()


def best_match(results, artist, title, year):
    best, best_score = None, 0
    for res in results:
        # Discogs title format is often "Artist - Title"
        rt = re.sub(r"^.*? - ", "", res.get("title", ""))
        ra = res.get("title", "").split(" - ")[0]
        score = (sim(rt, title) * 0.5 +
                 sim(ra, artist) * 0.3 +
                 (0.2 if year and str(year) == str(res.get("year", "")) else 0))
        if score > best_score:
            best, best_score = res, score
    return (best, best_score) if best_score > 0.35 else (None, 0)


# ── per-album enrichment ──────────────────────────────────────────────────────
def enrich_album(con, album_id, artist, title, year):
    cur = con.cursor()

    # 1. search
    try:
        results = search(artist, title)
    except Exception as e:
        print(f"  search error: {e}")
        return False
    time.sleep(DELAY)

    match, score = best_match(results, artist, title, year)
    if not match:
        cur.execute("UPDATE albums SET enriched=2 WHERE id=?", (album_id,))
        con.commit()
        return False

    # 2. fetch full release
    try:
        rel = get_release(match["id"])
    except Exception as e:
        print(f"  fetch error: {e}")
        return False
    time.sleep(DELAY)

    # store discogs_id
    cur.execute("UPDATE albums SET discogs_id=? WHERE id=?",
                (match["id"], album_id))

    # 3. credits from extraartists
    for ea in rel.get("extraartists", []):
        name = ea.get("name", "").strip()
        role = ea.get("role", "").strip()
        tracks = ea.get("tracks", "") or None
        did  = ea.get("id")
        if not name or not role:
            continue
        cat = categorise(role)
        cur.execute("""
            INSERT OR IGNORE INTO credits
              (album_id, person_name, role, role_category, tracks, discogs_artist_id)
            VALUES (?,?,?,?,?,?)
        """, (album_id, name, role, cat, tracks, did))

    # 4. track-level credits
    for track in rel.get("tracklist", []):
        for ea in track.get("extraartists", []):
            name = ea.get("name", "").strip()
            role = ea.get("role", "").strip()
            tname = track.get("position", "") + " " + track.get("title", "")
            did = ea.get("id")
            if not name or not role:
                continue
            cat = categorise(role)
            cur.execute("""
                INSERT OR IGNORE INTO credits
                  (album_id, person_name, role, role_category, tracks, discogs_artist_id)
                VALUES (?,?,?,?,?,?)
            """, (album_id, name, role, cat, tname.strip(), did))

    # 5. studios (companies with recording/mixing entity types)
    for company in rel.get("companies", []):
        etype = company.get("entity_type_name") or ""
        if not any(s in etype for s in ("Recorded", "Mixed", "Mastered")):
            continue
        sname = company.get("name", "").strip()
        sdid  = company.get("id")
        if not sname:
            continue
        cur.execute("INSERT OR IGNORE INTO studios (name, discogs_id) VALUES (?,?)",
                    (sname, sdid))
        sid = cur.execute("SELECT id FROM studios WHERE name=?",
                          (sname,)).fetchone()[0]
        cur.execute("""
            INSERT OR IGNORE INTO album_studios (album_id, studio_id, role)
            VALUES (?,?,?)
        """, (album_id, sid, etype))

    # 6. labels
    for lbl in rel.get("labels", []):
        lname = lbl.get("name", "").strip()
        ldid  = lbl.get("id")
        catno = lbl.get("catno", "")
        if not lname or lname.lower() == "not on label":
            continue
        cur.execute("INSERT OR IGNORE INTO labels (name, discogs_id) VALUES (?,?)",
                    (lname, ldid))
        lid = cur.execute("SELECT id FROM labels WHERE name=?",
                          (lname,)).fetchone()[0]
        cur.execute("""
            INSERT OR IGNORE INTO album_labels (album_id, label_id, catalog_number)
            VALUES (?,?,?)
        """, (album_id, lid, catno))

    cur.execute("UPDATE albums SET enriched=1 WHERE id=?", (album_id,))
    con.commit()
    return True


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA_EXTRA)

    todo = con.execute("""
        SELECT id, artist, title, year FROM albums
        WHERE enriched = 0 AND title != '' AND artist != ''
        ORDER BY total_plays DESC, id
    """).fetchall()

    total = con.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
    done  = con.execute("SELECT COUNT(*) FROM albums WHERE enriched > 0").fetchone()[0]
    print(f"Library: {total} albums, {done} already enriched, {len(todo)} to go")
    print(f"Estimated time: ~{len(todo)*2//60} min\n")

    ok = fail = 0
    for i, (aid, artist, title, year) in enumerate(todo, 1):
        label = f"{artist} — {title}"[:60]
        pct   = f"[{done+i}/{total}]"
        result = enrich_album(con, aid, artist, title, year)
        if result:
            ok += 1
            print(f"  {pct} ✓  {label}")
        else:
            fail += 1
            print(f"  {pct} ✗  {label}")

        if i % 50 == 0:
            c = con.execute("SELECT COUNT(*) FROM credits").fetchone()[0]
            s = con.execute("SELECT COUNT(*) FROM studios").fetchone()[0]
            print(f"\n  ── checkpoint: {c} credits, {s} studios so far ──\n")

    print(f"\nDone. Matched: {ok}  Not found: {fail}")
    c = con.execute("SELECT COUNT(*) FROM credits").fetchone()[0]
    s = con.execute("SELECT COUNT(*) FROM studios").fetchone()[0]
    l = con.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    print(f"Credits: {c}   Studios: {s}   Labels: {l}")
    con.close()


if __name__ == "__main__":
    main()
