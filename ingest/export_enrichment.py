"""
export_enrichment.py — Export enrichment data from local DB to shared corpus.

Dumps all credits, studios, labels, and artist relationships to
data/enrichment.json, keyed by "Artist|Album Title" so it's portable
across any library regardless of local album IDs.

Run once to seed the corpus, then run again after enrich_all.py
finishes to pick up any new albums.

Usage:  python3 ingest/export_enrichment.py
"""
import sqlite3, json
from pathlib import Path
from datetime import date
from collections import defaultdict

DB  = Path(__file__).parent.parent / "data" / "library.db"
OUT = Path(__file__).parent.parent / "data" / "enrichment.json"


def export():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    albums_out   = {}   # "Artist|Title" -> album entry
    artists_out  = {}   # "Artist Name"  -> artist entry

    # ── albums: base info ─────────────────────────────────────────────────────
    for row in con.execute("""
        SELECT id, artist, title, discogs_id, mb_release_id
        FROM albums
        WHERE enriched = 1
          AND title != ''
          AND artist NOT IN ('', 'Unknown', 'Various Artists')
    """):
        key = f"{row['artist']}|{row['title']}"
        albums_out[key] = {
            "discogs_id":    row["discogs_id"],
            "mb_release_id": row["mb_release_id"],
            "credits":       [],
            "studios":       [],
            "labels":        [],
        }

    print(f"Enriched albums: {len(albums_out)}")

    # ── credits ───────────────────────────────────────────────────────────────
    credit_count = 0
    for row in con.execute("""
        SELECT a.artist, a.title, c.person_name, c.role, c.role_category, c.tracks
        FROM credits c
        JOIN albums a ON a.id = c.album_id
        WHERE a.enriched = 1
          AND a.title != ''
          AND a.artist NOT IN ('', 'Unknown', 'Various Artists')
          AND c.person_name != ''
        ORDER BY a.artist, a.title, c.role_category, c.person_name
    """):
        key = f"{row['artist']}|{row['title']}"
        if key not in albums_out:
            continue
        albums_out[key]["credits"].append({
            "person":   row["person_name"],
            "role":     row["role"],
            "category": row["role_category"],
            "tracks":   row["tracks"],
        })
        credit_count += 1

    # ── studios ───────────────────────────────────────────────────────────────
    studio_count = 0
    for row in con.execute("""
        SELECT a.artist, a.title, s.name, als.role
        FROM album_studios als
        JOIN studios s  ON s.id  = als.studio_id
        JOIN albums  a  ON a.id  = als.album_id
        WHERE a.enriched = 1
          AND a.title != ''
          AND a.artist NOT IN ('', 'Unknown', 'Various Artists')
        ORDER BY a.artist, a.title
    """):
        key = f"{row['artist']}|{row['title']}"
        if key not in albums_out:
            continue
        albums_out[key]["studios"].append({
            "name": row["name"],
            "role": row["role"],
        })
        studio_count += 1

    # ── labels ────────────────────────────────────────────────────────────────
    label_count = 0
    for row in con.execute("""
        SELECT a.artist, a.title, l.name, al.catalog_number
        FROM album_labels al
        JOIN labels  l  ON l.id  = al.label_id
        JOIN albums  a  ON a.id  = al.album_id
        WHERE a.enriched = 1
          AND a.title != ''
          AND a.artist NOT IN ('', 'Unknown', 'Various Artists')
          AND l.name NOT LIKE '%Not On Label%'
        ORDER BY a.artist, a.title
    """):
        key = f"{row['artist']}|{row['title']}"
        if key not in albums_out:
            continue
        albums_out[key]["labels"].append({
            "name":           row["name"],
            "catalog_number": row["catalog_number"],
        })
        label_count += 1

    # ── artist relationships (MusicBrainz) ───────────────────────────────────
    rel_count = 0
    for row in con.execute("""
        SELECT ar.artist_id, a.name as artist_name, a.mb_artist_id,
               ar.related_name, ar.related_mb_id, ar.relation_type,
               ar.direction, ar.begin_year, ar.end_year, ar.ended
        FROM artist_relationships ar
        JOIN artists a ON a.id = ar.artist_id
        ORDER BY a.name
    """):
        name = row["artist_name"]
        if name not in artists_out:
            artists_out[name] = {
                "mb_artist_id":  row["mb_artist_id"],
                "relationships": [],
            }
        artists_out[name]["relationships"].append({
            "related_name":  row["related_name"],
            "related_mb_id": row["related_mb_id"],
            "relation_type": row["relation_type"],
            "direction":     row["direction"],
            "begin_year":    row["begin_year"],
            "end_year":      row["end_year"],
            "ended":         row["ended"],
        })
        rel_count += 1

    con.close()

    corpus = {
        "_meta": {
            "version":       1,
            "exported":      str(date.today()),
            "albums":        len(albums_out),
            "credits":       credit_count,
            "studios":       studio_count,
            "labels":        label_count,
            "artist_relationships": rel_count,
        },
        "albums":  albums_out,
        "artists": artists_out,
    }

    OUT.write_text(json.dumps(corpus, ensure_ascii=False, separators=(",", ":")))

    size_mb = OUT.stat().st_size / 1_048_576
    print(f"Credits:              {credit_count:,}")
    print(f"Studio links:         {studio_count:,}")
    print(f"Label links:          {label_count:,}")
    print(f"Artist relationships: {rel_count:,}")
    print(f"\nWritten → {OUT}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    export()
