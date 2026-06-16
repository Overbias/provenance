"""
build_graph.py — Build the 3D knowledge graph JSON from the enriched library.

Node types and base depths:
  album       0     (the surface — what you own)
  artist      50    (immediately obvious)
  genre       80    (obvious grouping)
  year        80    (era cohort)
  label       130   (slightly less obvious)
  writer      160   (songwriting connections)
  producer    200   (interesting territory)
  engineer    250   (getting deep)
  arranger    280
  studio      320   (deep — geographic/era clusters)
  musician    370   (rarefied — session players)

Depth is then ADJUSTED by frequency in the library:
  actual_depth = base_depth × (1 - 0.6 × (log(freq) / log(max_freq)))

A producer who touched 20 albums in your library floats toward the surface.
A session violinist who appears once sinks to the floor.
"""
import sqlite3, json, math, re
from pathlib import Path
from collections import defaultdict

DB   = Path(__file__).parent.parent / "data" / "library.db"
OUT  = Path(__file__).parent.parent / "data" / "graph.json"

BASE_DEPTH = {
    "album":    0,
    "artist":   50,
    "genre":    80,
    "year":     80,
    "label":    130,
    "writer":   160,
    "producer": 200,
    "arranger": 280,
    "engineer": 250,
    "studio":   320,
    "musician": 370,
    "other":    350,
}

# roles we skip (too noisy / not interesting for this graph)
SKIP_ROLES = re.compile(
    r"thank|design|layout|photo|art direct|illustrat|liner|"
    r"coordinat|management|legal|research|remaster|reissue|"
    r"compiled|supervised",
    re.I
)


def adjusted_depth(node_type, freq, max_freq):
    base = BASE_DEPTH.get(node_type, 300)
    if max_freq <= 1:
        return base
    factor = math.log(freq) / math.log(max_freq)
    return round(base * (1 - 0.6 * factor))


def slugify(s):
    return re.sub(r"[^a-z0-9_]", "_", s.lower())


def build():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Ensure enrichment tables exist (they're populated later by enrich_*.py)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS credits (
            id INTEGER PRIMARY KEY, album_id INTEGER, person_name TEXT,
            role TEXT, role_category TEXT, tracks TEXT);
        CREATE TABLE IF NOT EXISTS studios (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS album_studios (
            album_id INTEGER, studio_id INTEGER, role TEXT);
        CREATE TABLE IF NOT EXISTS labels (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS album_labels (album_id INTEGER, label_id INTEGER);
        CREATE TABLE IF NOT EXISTS artist_relationships (
            id INTEGER PRIMARY KEY, artist_id INTEGER, related_name TEXT,
            related_mb_id TEXT, relation_type TEXT, direction TEXT,
            begin_year INTEGER, end_year INTEGER, ended INTEGER DEFAULT 0);
    """)

    nodes = {}   # id -> node dict
    links = []   # {source, target, type}

    def add_node(nid, ntype, label, meta=None):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype,
                          "label": label, "freq": 0, **(meta or {})}
        nodes[nid]["freq"] += 1

    # ── albums ────────────────────────────────────────────────────────────────
    albums = con.execute("""
        SELECT a.id, a.artist, a.title, a.year, a.genre,
               a.track_count, a.total_plays, a.enriched,
               GROUP_CONCAT(DISTINCT t.artist) as track_artists
        FROM albums a
        LEFT JOIN tracks t ON t.album_artist = a.artist AND t.album = a.title
        WHERE a.title != '' AND a.artist NOT IN ('', 'Unknown', 'Various Artists')
        GROUP BY a.id
    """).fetchall()

    print(f"Building graph from {len(albums)} albums…")

    for alb in albums:
        aid  = f"album_{alb['id']}"
        meta = {"year": alb["year"], "plays": alb["total_plays"],
                "tracks": alb["track_count"], "enriched": alb["enriched"],
                "artist": alb["artist"]}
        add_node(aid, "album", f"{alb['title']}", meta)

        # ── artist ────────────────────────────────────────────────────────────
        if alb["artist"]:
            artid = f"artist_{slugify(alb['artist'])}"
            add_node(artid, "artist", alb["artist"])
            links.append({"source": aid, "target": artid, "type": "by"})

        # ── genre ─────────────────────────────────────────────────────────────
        if alb["genre"]:
            gid = f"genre_{slugify(alb['genre'])}"
            add_node(gid, "genre", alb["genre"])
            links.append({"source": aid, "target": gid, "type": "genre"})

        # ── year ──────────────────────────────────────────────────────────────
        if alb["year"] and 1900 < alb["year"] < 2030:
            yid = f"year_{alb['year']}"
            add_node(yid, "year", str(alb["year"]))
            links.append({"source": aid, "target": yid, "type": "released"})

    # ── credits (producer / engineer / musician / writer) ────────────────────
    # One node per person regardless of how many roles they hold.
    # Primary category = highest-priority role they appear in most often.
    CATEGORY_PRIORITY = ["producer", "engineer", "arranger", "writer", "musician", "other"]

    credits = con.execute("""
        SELECT c.album_id, c.person_name, c.role, c.role_category, c.tracks
        FROM credits c
        JOIN albums a ON a.id = c.album_id
        WHERE a.title != '' AND a.artist NOT IN ('', 'Unknown', 'Various Artists')
          AND c.person_name != ''
    """).fetchall()

    # accumulate per-person before building nodes so we can pick primary category
    from collections import defaultdict, Counter
    person_cats = defaultdict(Counter)   # name -> {cat: count}
    person_creds = []                    # filtered list

    for cr in credits:
        if SKIP_ROLES.search(cr["role"]):
            continue
        cat = cr["role_category"] or "other"
        person_cats[cr["person_name"]][cat] += 1
        person_creds.append((cr["album_id"], cr["person_name"], cr["role"],
                             cat, cr["tracks"]))

    def primary_cat(name):
        counts = person_cats[name]
        # pick the most frequent; break ties by CATEGORY_PRIORITY order
        return max(counts,
                   key=lambda c: (counts[c],
                                  -CATEGORY_PRIORITY.index(c)
                                  if c in CATEGORY_PRIORITY else -99))

    for album_id, name, role, cat, tracks in person_creds:
        nid = f"person_{slugify(name)}"
        aid = f"album_{album_id}"
        if aid not in nodes:
            continue
        # node type = primary category across ALL their credits
        pcat = primary_cat(name)
        add_node(nid, pcat, name)
        links.append({
            "source": aid, "target": nid,
            "type": role,
            "tracks": tracks or None,
        })

    # ── studios ───────────────────────────────────────────────────────────────
    studios = con.execute("""
        SELECT als.album_id, s.name, als.role
        FROM album_studios als JOIN studios s ON s.id = als.studio_id
        JOIN albums a ON a.id = als.album_id
        WHERE a.title != '' AND a.artist NOT IN ('', 'Unknown', 'Various Artists')
    """).fetchall()

    for st in studios:
        sid = f"studio_{slugify(st['name'])}"
        aid = f"album_{st['album_id']}"
        if aid not in nodes:
            continue
        add_node(sid, "studio", st["name"])
        links.append({"source": aid, "target": sid, "type": st["role"]})

    # ── labels ────────────────────────────────────────────────────────────────
    label_rows = con.execute("""
        SELECT al.album_id, l.name
        FROM album_labels al JOIN labels l ON l.id = al.label_id
        JOIN albums a ON a.id = al.album_id
        WHERE a.title != '' AND a.artist NOT IN ('', 'Unknown', 'Various Artists')
          AND l.name NOT LIKE '%Not On Label%'
    """).fetchall()

    for lr in label_rows:
        lid = f"label_{slugify(lr['name'])}"
        aid = f"album_{lr['album_id']}"
        if aid not in nodes:
            continue
        add_node(lid, "label", lr["name"])
        links.append({"source": aid, "target": lid, "type": "released_on"})

    # ── band memberships (MusicBrainz) ───────────────────────────────────────
    member_rows = con.execute("""
        SELECT ar.direction, ar.related_name, a.name as artist_name
        FROM artist_relationships ar
        JOIN artists a ON a.id = ar.artist_id
    """).fetchall()

    mb_links = 0
    for row in member_rows:
        a_slug = slugify(row["artist_name"])
        r_slug = slugify(row["related_name"])

        a_node = nodes.get(f"artist_{a_slug}") or nodes.get(f"person_{a_slug}")
        r_node = nodes.get(f"artist_{r_slug}") or nodes.get(f"person_{r_slug}")

        if not a_node or not r_node:
            continue

        # direction='backward': artist_name is the band, related_name is the member
        # direction='forward':  artist_name is the member, related_name is the band
        if row["direction"] == "backward":
            src, tgt = r_node["id"], a_node["id"]
        else:
            src, tgt = a_node["id"], r_node["id"]

        links.append({"source": src, "target": tgt, "type": "member_of"})
        mb_links += 1

    print(f"  {mb_links} band membership links added")

    con.close()

    # ── compute depths ────────────────────────────────────────────────────────
    max_freq = max(n["freq"] for n in nodes.values()) if nodes else 1
    for n in nodes.values():
        n["depth"] = adjusted_depth(n["type"], n["freq"], max_freq)

    # ── deduplicate links ─────────────────────────────────────────────────────
    seen = set()
    deduped = []
    for lk in links:
        key = (lk["source"], lk["target"], lk["type"])
        if key not in seen:
            seen.add(key)
            deduped.append(lk)

    # ── recommendation scores ─────────────────────────────────────────────────
    # For each album, sum the plays of albums that share a provenance node,
    # weighted by node type and inverse degree (rare connections score higher).
    # score = affinity / (own_plays + 1)  →  high means loved-by-proxy, unheard.
    _REC_WEIGHT = {"musician": 3.0, "producer": 2.5, "arranger": 2.0,
                   "engineer": 2.0, "writer": 1.5, "studio": 1.0, "label": 0.5}
    _REC_NOISE  = re.compile(
        r'\bdisc\s*[2-9]\b|\bcd\s*[2-9]\b|\b(single|ep)\b'
        r'|\b(remix(es)?|mixes?)\b|\bgreatest\s+hits?\b|\bbest\s+of\b'
        r'|\bessential\b|\banthology\b|\bcollection\b|\bchillout\b'
        r'|\bsoundtrack\b|\bmotion\s+picture\b|\boriginal\s+(score|music)\b'
        r'|\bmusic\s+from\b|\bpresents\b|\bvarious\s+artists?\b'
        r'|\bcompilation\b|\bchristmas\b|\bholiday\b', re.I)

    rec_adj = defaultdict(set)
    for lk in deduped:
        rec_adj[lk["source"]].add(lk["target"])
        rec_adj[lk["target"]].add(lk["source"])

    rec_affinity = defaultdict(float)
    for nid, node in nodes.items():
        if node["type"] not in _REC_WEIGHT:
            continue
        alb_nbrs = [nb for nb in rec_adj[nid] if nodes.get(nb, {}).get("type") == "album"]
        if len(alb_nbrs) < 2:
            continue
        w, inv_d = _REC_WEIGHT[node["type"]], 1.0 / len(alb_nbrs)
        for aid_a in alb_nbrs:
            for aid_b in alb_nbrs:
                if aid_a != aid_b:
                    rec_affinity[aid_a] += (nodes[aid_b].get("plays") or 0) * w * inv_d

    rec_count = 0
    for nid, aff in rec_affinity.items():
        n = nodes.get(nid)
        if not n or n["type"] != "album" or _REC_NOISE.search(n.get("label", "")):
            continue
        n["rec_score"] = round(aff / ((n.get("plays") or 0) + 1), 1)
        rec_count += 1
    print(f"  {rec_count} albums scored for recommendations")

    graph = {"nodes": list(nodes.values()), "links": deduped}
    OUT.write_text(json.dumps(graph, ensure_ascii=False))

    # stats
    type_counts = defaultdict(int)
    for n in nodes.values():
        type_counts[n["type"]] += 1

    print(f"\nGraph written to {OUT}")
    print(f"  {len(nodes):,} nodes   {len(deduped):,} links")
    print(f"\n  Node breakdown:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {c:5d}  {t}")


if __name__ == "__main__":
    build()
