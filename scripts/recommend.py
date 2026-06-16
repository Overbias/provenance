"""
recommend.py — Surface albums you own but underlisten relative to their provenance neighbours.

Algorithm (2-hop graph traversal):
  For each album A, find every album B that shares a provenance intermediary
  (musician, producer, engineer, etc). B's play count contributes to A's
  "affinity score", weighted by:
    - intermediary type (session musician > label)
    - 1/degree of the intermediary (rare connections are stronger signals)

  recommendation_score = affinity / (own_plays + 1)

  High score = surrounded by music you love, but barely played yourself.

Run: python3 scripts/recommend.py
"""
import json, re
from pathlib import Path
from collections import defaultdict

GRAPH = Path(__file__).parent.parent / "data" / "graph.json"

# Titles matching these patterns are excluded from recommendations
_NOISE = re.compile(
    r'\bdisc\s*[2-9]\b'            # Disc 2, Disc 3 …
    r'|\bcd\s*[2-9]\b'             # CD 2 …
    r'|\b(single|ep)\b'            # singles and EPs
    r'|\b(remix(es)?|mixes?)\b'    # remix albums
    r'|\bgreatest\s+hits?\b'
    r'|\bbest\s+of\b'
    r'|\bessential\b'
    r'|\banthology\b'
    r'|\bcollection\b'
    r'|\bchillout\b'
    r'|\bsoundtrack\b'
    r'|\bmotion\s+picture\b'
    r'|\boriginal\s+(score|music)\b'
    r'|\bmusic\s+from\b'
    r'|\bpresents\b'
    r'|\bvarious\s+artists?\b'
    r'|\bcompilation\b'
    r'|\bchristmas\b'
    r'|\bholiday\b',
    re.IGNORECASE,
)

def is_noise(label):
    return bool(_NOISE.search(label))

# Contribution weight per intermediary type — genre/year excluded (too broad)
TYPE_WEIGHT = {
    "musician":  3.0,
    "producer":  2.5,
    "arranger":  2.0,
    "engineer":  2.0,
    "writer":    1.5,
    "studio":    1.0,
    "label":     0.5,
}

def main():
    print("Loading graph…")
    data = json.loads(GRAPH.read_text())
    nodes  = {n["id"]: n for n in data["nodes"]}
    links  = data["links"]

    # Adjacency list
    adj = defaultdict(set)
    for lk in links:
        src = lk["source"] if isinstance(lk["source"], str) else lk["source"]["id"]
        tgt = lk["target"] if isinstance(lk["target"], str) else lk["target"]["id"]
        adj[src].add(tgt)
        adj[tgt].add(src)

    # For each qualifying intermediary, collect its connected album IDs
    inter_albums = {}
    for nid, node in nodes.items():
        if node["type"] not in TYPE_WEIGHT:
            continue
        alb_neighbours = [nb for nb in adj[nid] if nodes.get(nb, {}).get("type") == "album"]
        if len(alb_neighbours) >= 2:
            inter_albums[nid] = alb_neighbours

    print(f"  {len(inter_albums):,} intermediary nodes connecting ≥2 albums")

    # Accumulate affinity: for each album A, sum the plays of every album B
    # that shares a provenance node with A, weighted by type and rarity.
    affinity = defaultdict(float)
    for inter_id, alb_ids in inter_albums.items():
        node    = nodes[inter_id]
        weight  = TYPE_WEIGHT[node["type"]]
        inv_deg = 1.0 / len(alb_ids)   # rarer connections score higher
        for aid_a in alb_ids:
            for aid_b in alb_ids:
                if aid_a == aid_b:
                    continue
                plays_b = nodes[aid_b].get("plays") or 0
                affinity[aid_a] += plays_b * weight * inv_deg

    # Score every album (skip compilations, discs, singles, soundtracks)
    results = []
    skipped = 0
    for nid, node in nodes.items():
        if node["type"] != "album":
            continue
        aff = affinity.get(nid, 0)
        if aff == 0:
            continue
        label = node.get("label", "?")
        if is_noise(label):
            skipped += 1
            continue
        own   = node.get("plays") or 0
        score = aff / (own + 1)
        results.append({
            "score": score,
            "plays": own,
            "affinity": aff,
            "label":  label,
            "artist": node.get("artist", ""),
        })

    results.sort(key=lambda r: -r["score"])

    def fmt(r):
        title = f"{r['artist']} — {r['label']}" if r["artist"] else r["label"]
        return f"  {r['score']:8.1f}  plays={r['plays']:4d}  {title}"

    # ── Top recommendations (any play count) ──────────────────────────────────
    print(f"\n{'='*70}")
    print("TOP 30  high provenance affinity, low own plays")
    print(f"{'='*70}")
    print(f"  {'Score':>8}  {'Plays':>9}  Album")
    print(f"  {'-'*65}")
    for r in results[:30]:
        print(fmt(r))

    # ── Never played ──────────────────────────────────────────────────────────
    never = [r for r in results if r["plays"] == 0]
    print(f"\n{'='*70}")
    print(f"NEVER PLAYED  ({len(never)} albums with plays=0, ranked by affinity)")
    print(f"{'='*70}")
    print(f"  {'Score':>8}  {'Plays':>9}  Album")
    print(f"  {'-'*65}")
    for r in never[:30]:
        print(fmt(r))

    # ── Rarely played (1–5 plays) ─────────────────────────────────────────────
    rare = [r for r in results if 1 <= r["plays"] <= 5]
    print(f"\n{'='*70}")
    print(f"RARELY PLAYED  (1–5 plays, {len(rare)} albums)")
    print(f"{'='*70}")
    print(f"  {'Score':>8}  {'Plays':>9}  Album")
    print(f"  {'-'*65}")
    for r in rare[:20]:
        print(fmt(r))

    # ── Stats ─────────────────────────────────────────────────────────────────
    total_albums = sum(1 for n in nodes.values() if n["type"] == "album")
    scored       = len(results)
    print(f"\n-- Stats --------------------------------------------------------------------")
    print(f"  Albums total:    {total_albums:,}")
    print(f"  Filtered out:    {skipped:,}  (compilations, discs, singles, soundtracks)")
    print(f"  Albums scored:   {scored:,}  ({scored/total_albums*100:.0f}%)")
    print(f"  Never played:    {len(never):,}")
    print(f"  Rarely played:   {len(rare):,}  (1–5 plays)")


if __name__ == "__main__":
    main()
