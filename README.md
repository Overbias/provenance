# Provenance

Your music library as a 3D knowledge graph. Albums, artists, producers, engineers, studios and session musicians — rendered as a navigable constellation. The rarer the connection, the deeper it sits.

![Provenance screenshot](web/screenshot.png)

## Quick start

```bash
git clone https://github.com/bengeorgiades/provenance.git
cd provenance
python3 setup.py
```

That's it. Opens in your browser at `http://localhost:8765`.

**Requires:** macOS, Python 3 (pre-installed), Music.app with a library.

If your library XML isn't found automatically:
> Music.app → File → Library → Export Library…

Then:
```bash
python3 setup.py ~/Desktop/Library.xml
```

## What you get immediately

- Your albums, artists, genres and years as a navigable 3D graph
- Click any node to expand its constellation of connections
- DISCOVER mode — surfaces albums you own but have barely played, ranked by how connected they are to things you love

## Going deeper

For producer, engineer, studio and session musician connections, run the enrichment scripts. These call free public APIs and take a few hours each.

```bash
python3 ingest/enrich_discogs.py        # credits, studios, labels
python3 ingest/enrich_musicbrainz.py    # band memberships, release IDs
python3 graph/build_graph.py            # rebuild graph
python3 api/server.py                   # restart server
```

## Play in Music

Clicking **▶ Play in Music** in the detail panel triggers playback in Music.app via AppleScript. Works on your local machine only — requires the server running.

## The idea

Most music recommendation is popularity-based. This is provenance-based: the graph connects albums through the people and places that made them. A producer who worked on six albums you love but whose other records you've never heard — that's the signal.

Built with [3d-force-graph](https://github.com/vasturiano/3d-force-graph) and Three.js.
