"""
server.py — Minimal local server for the Music Graph.
Run: python3 api/server.py
Opens at http://localhost:8765
"""
import http.server, socketserver, os, json, subprocess
from pathlib import Path

PORT    = 8765
WEB_DIR = Path(__file__).parent.parent / "web"
DATA_DIR = Path(__file__).parent.parent / "data"


def applescript_str(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')

def play_in_music(artist=None, album=None):
    """Tell Music.app to play matching tracks. Returns track count found.
    For album nodes: tries exact album+artist, falls back to artist-only."""
    a_esc = applescript_str(artist or '')
    b_esc = applescript_str(album or '')

    if album and artist:
        # Try exact album+artist first, fall back to artist-only
        script = f'''
            tell application "Music"
                set trks to (every track of library playlist 1 whose album is "{b_esc}" and artist is "{a_esc}")
                if (count of trks) is 0 then
                    set trks to (every track of library playlist 1 whose artist is "{a_esc}")
                end if
                if (count of trks) > 0 then
                    play item 1 of trks
                end if
                return count of trks
            end tell
        '''
    elif artist:
        script = f'''
            tell application "Music"
                set trks to (every track of library playlist 1 whose artist is "{a_esc}")
                if (count of trks) > 0 then play item 1 of trks
                return count of trks
            end tell
        '''
    else:
        return 0

    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        if self.path == '/graph.json':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write((DATA_DIR / 'graph.json').read_bytes())
            return

        if self.path.startswith('/play'):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            artist = qs.get('artist', [None])[0]
            album  = qs.get('album',  [None])[0]
            count = play_in_music(artist=artist, album=album)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(str(count).encode())
            return

        super().do_GET()

    def log_message(self, fmt, *args):
        pass   # suppress request noise


if __name__ == '__main__':
    os.chdir(WEB_DIR)
    with socketserver.TCPServer(('', PORT), Handler) as httpd:
        url = f'http://localhost:{PORT}'
        print(f'Provenance → {url}')
        subprocess.Popen(['open', url])
        httpd.serve_forever()
