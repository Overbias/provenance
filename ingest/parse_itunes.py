"""
parse_itunes.py — Parse iTunes Library.xml into SQLite.
Run: python3 parse_itunes.py ~/Desktop/Library.xml
"""
import plistlib, sqlite3, sys, os
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "library.db"
DB.parent.mkdir(exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY,
    itunes_id   INTEGER UNIQUE,
    name        TEXT,
    artist      TEXT,
    album_artist TEXT,
    album       TEXT,
    year        INTEGER,
    genre       TEXT,
    track_num   INTEGER,
    disc_num    INTEGER,
    duration_ms INTEGER,
    play_count  INTEGER DEFAULT 0,
    rating      INTEGER DEFAULT 0,
    date_added  TEXT
);

CREATE TABLE IF NOT EXISTS albums (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artist      TEXT,       -- album artist (normalised)
    title       TEXT,
    year        INTEGER,
    genre       TEXT,
    track_count INTEGER,
    total_plays INTEGER DEFAULT 0,
    -- enrichment status
    discogs_id  INTEGER,
    mb_release_id TEXT,
    enriched    INTEGER DEFAULT 0,
    UNIQUE(artist, title)
);

CREATE TABLE IF NOT EXISTS artists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE,
    track_count INTEGER DEFAULT 0,
    mb_artist_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_tracks_album  ON tracks(album_artist, album);
CREATE INDEX IF NOT EXISTS idx_albums_artist ON albums(artist);
"""


def normalise(s):
    return (s or "").strip()


def main(xml_path):
    print(f"Loading {xml_path} …")
    with open(xml_path, "rb") as f:
        lib = plistlib.load(f)

    tracks = lib["Tracks"]
    print(f"  {len(tracks)} tracks found")

    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    cur = con.cursor()

    album_acc = {}   # (artist, title) → {year, genre, plays, track_count}

    for tid, t in tracks.items():
        name         = normalise(t.get("Name"))
        artist       = normalise(t.get("Artist"))
        album_artist = normalise(t.get("Album Artist") or artist)
        album        = normalise(t.get("Album"))
        year         = t.get("Year")
        genre        = normalise(t.get("Genre"))
        track_num    = t.get("Track Number")
        disc_num     = t.get("Disc Number")
        duration     = t.get("Total Time")
        plays        = t.get("Play Count", 0)
        rating       = t.get("Rating", 0)
        date_added   = str(t.get("Date Added", ""))

        cur.execute("""
            INSERT OR IGNORE INTO tracks
              (itunes_id,name,artist,album_artist,album,year,genre,
               track_num,disc_num,duration_ms,play_count,rating,date_added)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (int(tid), name, artist, album_artist, album, year, genre,
              track_num, disc_num, duration, plays, rating, date_added))

        # accumulate album stats
        key = (album_artist, album)
        if key not in album_acc:
            album_acc[key] = {"year": year, "genre": genre,
                              "plays": 0, "count": 0}
        album_acc[key]["plays"] += plays or 0
        album_acc[key]["count"] += 1
        if not album_acc[key]["year"] and year:
            album_acc[key]["year"] = year

    # insert albums
    for (artist, title), info in album_acc.items():
        cur.execute("""
            INSERT OR IGNORE INTO albums
              (artist, title, year, genre, track_count, total_plays)
            VALUES (?,?,?,?,?,?)
        """, (artist, title, info["year"], info["genre"],
              info["count"], info["plays"]))

    # insert artists
    artist_plays = {}
    for (artist, _), info in album_acc.items():
        artist_plays[artist] = artist_plays.get(artist, 0) + info["count"]
    for artist, count in artist_plays.items():
        cur.execute("""
            INSERT OR IGNORE INTO artists (name, track_count)
            VALUES (?,?)
            ON CONFLICT(name) DO UPDATE SET track_count = track_count + excluded.track_count
        """, (artist, count))

    con.commit()
    con.close()

    # summary
    con2 = sqlite3.connect(DB)
    print(f"\n  ✓ Inserted into {DB}")
    print(f"  Tracks  : {con2.execute('SELECT COUNT(*) FROM tracks').fetchone()[0]}")
    print(f"  Albums  : {con2.execute('SELECT COUNT(*) FROM albums').fetchone()[0]}")
    print(f"  Artists : {con2.execute('SELECT COUNT(*) FROM artists').fetchone()[0]}")
    top = con2.execute(
        "SELECT artist, title, total_plays FROM albums ORDER BY total_plays DESC LIMIT 10"
    ).fetchall()
    print(f"\n  Top 10 most-played albums:")
    for artist, title, plays in top:
        print(f"    {plays:5d}  {artist} — {title}")
    con2.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Desktop/Library.xml")
    main(path)
