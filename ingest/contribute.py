"""
contribute.py — Merge your unique enrichment into the shared corpus.

Finds albums you've enriched locally that aren't in data/enrichment.json,
adds them, and tells you how to share them back via GitHub.

Run after enrich_all.py has finished filling your unique albums.

Usage:  python3 ingest/contribute.py
"""
import sqlite3, json
from pathlib import Path
from datetime import date

DB     = Path(__file__).parent.parent / "data" / "library.db"
CORPUS = Path(__file__).parent.parent / "data" / "enrichment.json"


def export_album(con, album_id, discogs_id, mb_release_id):
    """Build a corpus entry for one album."""
    entry = {
        "discogs_id":    discogs_id,
        "mb_release_id": mb_release_id,
        "credits":       [],
        "studios":       [],
        "labels":        [],
    }

    for c in con.execute("""
        SELECT person_name, role, role_category, tracks
        FROM credits WHERE album_id = ?
        ORDER BY role_category, person_name
    """, (album_id,)):
        entry["credits"].append({
            "person":   c["person_name"],
            "role":     c["role"],
            "category": c["role_category"],
            "tracks":   c["tracks"],
        })

    for s in con.execute("""
        SELECT s.name, als.role
        FROM album_studios als JOIN studios s ON s.id = als.studio_id
        WHERE als.album_id = ?
    """, (album_id,)):
        entry["studios"].append({"name": s["name"], "role": s["role"]})

    for l in con.execute("""
        SELECT l.name, al.catalog_number
        FROM album_labels al JOIN labels l ON l.id = al.label_id
        WHERE al.album_id = ? AND l.name NOT LIKE '%Not On Label%'
    """, (album_id,)):
        entry["labels"].append({"name": l["name"], "catalog_number": l["catalog_number"]})

    return entry


def contribute():
    if not CORPUS.exists():
        print("No corpus found. Run export_enrichment.py first.")
        return

    corpus  = json.loads(CORPUS.read_text())
    existing_keys = set(corpus["albums"].keys())

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # ── find locally enriched albums not yet in corpus ────────────────────────
    new_albums = {}
    for row in con.execute("""
        SELECT id, artist, title, discogs_id, mb_release_id
        FROM albums
        WHERE enriched = 1
          AND title != ''
          AND artist NOT IN ('', 'Unknown', 'Various Artists')
        ORDER BY artist, title
    """):
        key = f"{row['artist']}|{row['title']}"
        if key not in existing_keys:
            new_albums[key] = (row["id"], row["discogs_id"], row["mb_release_id"])

    if not new_albums:
        print("Nothing new to contribute — your enrichment is already in the corpus.")
        con.close()
        return

    print(f"Found {len(new_albums)} new albums to contribute:")

    added_credits = added_studios = added_labels = 0
    for key, (album_id, discogs_id, mb_release_id) in new_albums.items():
        entry = export_album(con, album_id, discogs_id, mb_release_id)
        corpus["albums"][key] = entry
        added_credits += len(entry["credits"])
        added_studios += len(entry["studios"])
        added_labels  += len(entry["labels"])
        artist, title = key.split("|", 1)
        print(f"  + {artist} — {title}  "
              f"({len(entry['credits'])} credits, "
              f"{len(entry['studios'])} studios, "
              f"{len(entry['labels'])} labels)")

    # ── new artist relationships ───────────────────────────────────────────────
    existing_artists = set(corpus.get("artists", {}).keys())
    added_rels = 0
    for row in con.execute("""
        SELECT a.name as artist_name, a.mb_artist_id,
               ar.related_name, ar.related_mb_id, ar.relation_type,
               ar.direction, ar.begin_year, ar.end_year, ar.ended
        FROM artist_relationships ar
        JOIN artists a ON a.id = ar.artist_id
        ORDER BY a.name
    """):
        name = row["artist_name"]
        if name not in corpus["artists"]:
            corpus["artists"][name] = {
                "mb_artist_id":  row["mb_artist_id"],
                "relationships": [],
            }
        # add relationship if not already present
        rel = {
            "related_name":  row["related_name"],
            "related_mb_id": row["related_mb_id"],
            "relation_type": row["relation_type"],
            "direction":     row["direction"],
            "begin_year":    row["begin_year"],
            "end_year":      row["end_year"],
            "ended":         row["ended"],
        }
        existing_rels = corpus["artists"][name]["relationships"]
        if not any(r["related_mb_id"] == rel["related_mb_id"]
                   and r["relation_type"] == rel["relation_type"]
                   for r in existing_rels):
            existing_rels.append(rel)
            added_rels += 1

    con.close()

    # ── update metadata ───────────────────────────────────────────────────────
    corpus["_meta"].update({
        "exported": str(date.today()),
        "albums":   len(corpus["albums"]),
        "credits":  corpus["_meta"].get("credits", 0) + added_credits,
        "studios":  corpus["_meta"].get("studios", 0) + added_studios,
        "labels":   corpus["_meta"].get("labels",  0) + added_labels,
        "artist_relationships": corpus["_meta"].get("artist_relationships", 0) + added_rels,
    })

    CORPUS.write_text(json.dumps(corpus, ensure_ascii=False, separators=(",", ":")))

    size_mb = CORPUS.stat().st_size / 1_048_576
    print(f"\nCorpus updated → {CORPUS}  ({size_mb:.1f} MB)")
    print(f"  New albums:      {len(new_albums):,}")
    print(f"  New credits:     {added_credits:,}")
    print(f"  New studios:     {added_studios:,}")
    print(f"  New labels:      {added_labels:,}")
    print(f"  New artist rels: {added_rels:,}")
    print(f"  Total albums:    {corpus['_meta']['albums']:,}")

    print("""
To share your discoveries:

  If you have push access:
    git add data/enrichment.json
    git commit -m "Contribute enrichment: N new albums"
    git push

  Otherwise, open a pull request on GitHub with the updated
  data/enrichment.json — every new album helps the next person.
""")


if __name__ == "__main__":
    contribute()
