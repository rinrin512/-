"""Loopback-only personal HTML archive helper. Stop with Ctrl+C."""
import argparse
import json
from pathlib import Path
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
CAPTURE_LOCK = threading.Lock()


def capture(url):
    from playwright.sync_api import sync_playwright

    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('http:// または https:// のURLを入力してください。')
    source = (ROOT / 'personal-web-archive.html').read_text(encoding='utf-8')
    script = re.search(r'function capturePage\(.*?(?=\nconst \$=)', source, re.S).group(0)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=False)
            page = context.new_page()
            page.on('dialog', lambda dialog: dialog.dismiss())
            response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
            if response and response.status >= 400:
                raise ValueError(f'対象サイトがHTTP {response.status}を返しました。復旧後に再試行してください。')
            page.wait_for_timeout(1500)
            # Bounded scrolling loads common lazy images without following infinite feeds.
            for _ in range(12):
                at_bottom = page.evaluate('''() => { window.scrollBy(0,900); return window.scrollY + innerHeight >= document.documentElement.scrollHeight; }''')
                page.wait_for_timeout(200)
                if at_bottom:
                    break
            page.evaluate('window.scrollTo(0,0)')
            return page.evaluate('async () => {' + script + '; return await capturePage(true); }')
        finally:
            browser.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not write captured URLs or query strings to logs.

    def allowed_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def send(self, status, body, content_type='application/json; charset=utf-8'):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.allowed_host():
            self.send(403, '{}')
        elif self.path == '/':
            html = (ROOT / 'personal-web-archive.html').read_text(encoding='utf-8')
            self.send(200, html.replace('__LOCAL_ARCHIVE_TOKEN__', TOKEN), 'text/html; charset=utf-8')
        else:
            self.send(404, '{}')

    def do_POST(self):
        expected_origin = f'http://127.0.0.1:{self.server.server_port}'
        if (not self.allowed_host() or self.headers.get('Origin') != expected_origin
                or self.headers.get('X-Archive-Token') != TOKEN):
            self.send(403, json.dumps({'error': 'この画面から操作してください。'}, ensure_ascii=False))
            return
        if self.path != '/api/capture':
            self.send(404, '{}')
            return
        if not CAPTURE_LOCK.acquire(blocking=False):
            self.send(409, json.dumps({'error': '別のページを取得中です。'}, ensure_ascii=False))
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise ValueError('URLが長すぎるか、リクエストが空です。')
            data = json.loads(self.rfile.read(length))
            url = data.get('url', '')
            if not isinstance(url, str):
                raise ValueError('URLを入力してください。')
            result = capture(url.strip())
            self.send(200, json.dumps(result, ensure_ascii=False))
        except Exception as error:
            self.send(400, json.dumps({'error': str(error)[:1200]}, ensure_ascii=False))
        finally:
            CAPTURE_LOCK.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    url = f'http://127.0.0.1:{server.server_port}/'
    print(f'Personal web archive: {url}\nStop: Ctrl+C', flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
