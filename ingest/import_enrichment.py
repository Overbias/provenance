"""
import_enrichment.py — Import shared enrichment corpus into local DB.

Matches corpus entries to local albums by "Artist|Title" key.
Skips albums not in the local library. Skips rows already present.
Safe to run multiple times.

Called automatically by setup.py after parse_itunes.py.

Usage:  python3 ingest/import_enrichment.py
"""
import sqlite3, json
from pathlib import Path

DB     = Path(__file__).parent.parent / "data" / "library.db"
CORPUS = Path(__file__).parent.parent / "data" / "enrichment.json"


def import_corpus():
    if not CORPUS.exists():
        print("No enrichment corpus found — skipping import.")
        return

    corpus = json.loads(CORPUS.read_text())
    meta   = corpus.get("_meta", {})
    print(f"Corpus: {meta.get('albums', '?')} albums, "
          f"{meta.get('credits', '?')} credits  "
          f"(exported {meta.get('exported', '?')})")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Build local album lookup: "Artist|Title" -> id
    local_albums = {
        f"{r['artist']}|{r['title']}": r['id']
        for r in con.execute("SELECT id, artist, title FROM albums")
    }

    matched = 0
    credits_added = studios_added = labels_added = 0

    for key, entry in corpus["albums"].items():
        album_id = local_albums.get(key)
        if not album_id:
            continue
        matched += 1

        # ── update discogs_id / mb_release_id if not already set ─────────────
        con.execute("""
            UPDATE albums SET
                discogs_id    = COALESCE(discogs_id,    ?),
                mb_release_id = COALESCE(mb_release_id, ?),
                enriched      = 1
            WHERE id = ?
        """, (entry.get("discogs_id"), entry.get("mb_release_id"), album_id))

        # ── credits ───────────────────────────────────────────────────────────
        for c in entry.get("credits", []):
            try:
                con.execute("""
                    INSERT OR IGNORE INTO credits
                        (album_id, person_name, role, role_category, tracks)
                    VALUES (?, ?, ?, ?, ?)
                """, (album_id, c["person"], c["role"], c["category"], c.get("tracks")))
                credits_added += con.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass

        # ── studios ───────────────────────────────────────────────────────────
        for s in entry.get("studios", []):
            try:
                con.execute("INSERT OR IGNORE INTO studios (name) VALUES (?)", (s["name"],))
                sid = con.execute("SELECT id FROM studios WHERE name = ?", (s["name"],)).fetchone()[0]
                con.execute("""
                    INSERT OR IGNORE INTO album_studios (album_id, studio_id, role)
                    VALUES (?, ?, ?)
                """, (album_id, sid, s["role"]))
                studios_added += con.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass

        # ── labels ────────────────────────────────────────────────────────────
        for l in entry.get("labels", []):
            try:
                con.execute("INSERT OR IGNORE INTO labels (name) VALUES (?)", (l["name"],))
                lid = con.execute("SELECT id FROM labels WHERE name = ?", (l["name"],)).fetchone()[0]
                con.execute("""
                    INSERT OR IGNORE INTO album_labels (album_id, label_id, catalog_number)
                    VALUES (?, ?, ?)
                """, (album_id, lid, l.get("catalog_number")))
                labels_added += con.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass

    # ── artist relationships ──────────────────────────────────────────────────
    rels_added = 0
    for artist_name, entry in corpus.get("artists", {}).items():
        # ensure artist row exists and has mb_artist_id
        con.execute("INSERT OR IGNORE INTO artists (name) VALUES (?)", (artist_name,))
        con.execute("""
            UPDATE artists SET mb_artist_id = COALESCE(mb_artist_id, ?)
            WHERE name = ?
        """, (entry.get("mb_artist_id"), artist_name))

        artist_row = con.execute(
            "SELECT id FROM artists WHERE name = ?", (artist_name,)
        ).fetchone()
        if not artist_row:
            continue
        artist_id = artist_row[0]

        for r in entry.get("relationships", []):
            try:
                con.execute("""
                    INSERT OR IGNORE INTO artist_relationships
                        (artist_id, related_name, related_mb_id,
                         relation_type, direction, begin_year, end_year, ended)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (artist_id, r["related_name"], r.get("related_mb_id"),
                      r["relation_type"], r["direction"],
                      r.get("begin_year"), r.get("end_year"), r.get("ended", 0)))
                rels_added += con.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass

    con.commit()
    con.close()

    total = credits_added + studios_added + labels_added + rels_added
    print(f"Matched {matched} albums in your library")
    print(f"  Credits added:       {credits_added:,}")
    print(f"  Studio links added:  {studios_added:,}")
    print(f"  Label links added:   {labels_added:,}")
    print(f"  Relationships added: {rels_added:,}")
    print(f"  Total rows:          {total:,}")


if __name__ == "__main__":
    import_corpus()
