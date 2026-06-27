# Provenance

Your music library as a 3D knowledge graph. Albums, artists, producers, engineers, studios and session musicians — rendered as a navigable constellation. The rarer the connection, the deeper it sits.

![Provenance screenshot](web/screenshot.png)

## Try it first

Download **[bundle.html](web/bundle.html)** and open it in your browser — no setup, no Python, no server. You'll see a real library mapped as a 3D knowledge graph. When you're ready to see your own:

---

## Quick start

```bash
git clone https://github.com/Overbias/provenance.git
cd provenance
python3 setup.py
```

Opens in your browser at `http://localhost:8765`.

**Requires:** macOS, Python 3 (pre-installed on most Macs), Music.app with a library.

If your library XML isn't found automatically:
> Music.app → File → Library → Export Library…

Then:
```bash
python3 setup.py ~/Desktop/Library.xml
```

---

## Every time after that

Double-click **`Start Provenance.command`** in the provenance folder.

---

## What you get immediately

- Your albums, artists, genres and years as a navigable 3D graph
- A shared enrichment corpus — producer, engineer, studio and label connections for thousands of albums, imported instantly
- Click any node to expand its constellation of connections
- DISCOVER mode — surfaces albums you own but have barely played, ranked by how connected they are to things you love
- ▶ Play in Music — click any album or artist node to play it in Music.app

---

## Going deeper

For even richer connections on albums not yet in the shared corpus, run the enrichment scripts. These call free public APIs and take a few hours each. They start automatically in the background after setup — you'll notice the graph filling in while you explore.

To also enrich via Discogs (credits, studios, labels):

1. Create a free account at [discogs.com](https://www.discogs.com)
2. Go to Settings → Developers → Generate token
3. Add one line to a file called `.env` in the provenance folder:
   ```
   DISCOGS_TOKEN=your_token_here
   ```

Restart Provenance — Discogs enrichment kicks off automatically.

---

## Updating an existing install

```bash
git pull
python3 ingest/import_enrichment.py
python3 graph/build_graph.py
```

Then refresh your browser. The shared corpus grows with each contributor — pulling regularly gets you new connections.

---

## Contributing your discoveries

After enrichment finishes, run:

```bash
python3 ingest/contribute.py
```

This finds albums you've enriched that aren't in the shared corpus and merges them in. Follow the printed instructions to open a pull request — every new album helps the next person.

---

## The idea

Most music recommendation is popularity-based. This is provenance-based: the graph connects albums through the people and places that made them. A producer who worked on six albums you love but whose other records you've never heard — that's the signal.

Built with [3d-force-graph](https://github.com/vasturiano/3d-force-graph) and Three.js.
