"""HTTP server for ham-cw keyer web interface.

Serves a single-page web UI and a small JSON REST API.
Runs in a background thread so the keyer loop stays on time.
"""

import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

_MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.js':   'application/javascript; charset=utf-8',
    '.png':  'image/png',
    '.ico':  'image/x-icon',
}


class _ThreadedHTTP(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class WebServer:
    """Thin wrapper around a threaded HTTP server."""

    def __init__(self, *, get_status, get_config, update_config,
                 send_text, stop_send, test_tone, scan_pins, port=80):
        self._get_status = get_status
        self._get_config = get_config
        self._update_config = update_config
        self._send_text = send_text
        self._stop_send = stop_send
        self._test_tone = test_tone
        self._scan_pins = scan_pins
        self._port = port
        self._server = None
        self._thread = None

    def start(self):
        handler = self._make_handler()
        self._server = _ThreadedHTTP(('0.0.0.0', self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True, name='web-server')
        self._thread.start()
        print(f"ham-cw: web UI at http://0.0.0.0:{self._port}")

    def stop(self):
        if self._server:
            self._server.shutdown()

    def _make_handler(self):
        get_status = self._get_status
        get_config = self._get_config
        update_config = self._update_config
        send_text = self._send_text
        stop_send = self._stop_send
        test_tone = self._test_tone
        scan_pins = self._scan_pins

        class Handler(BaseHTTPRequestHandler):

            def log_message(self, fmt, *args):
                pass

            def _json_response(self, data, code=200):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)

            def _serve_file(self, fpath, ctype):
                try:
                    with open(fpath, 'rb') as f:
                        body = f.read()
                except FileNotFoundError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', len(body))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlparse(self.path).path

                if path in ('/', '/index.html'):
                    self._serve_file(
                        os.path.join(_STATIC_DIR, 'index.html'),
                        'text/html; charset=utf-8')
                    return

                if path == '/api/status':
                    self._json_response(get_status())
                    return

                if path == '/api/config':
                    self._json_response(get_config())
                    return

                if path == '/api/scan':
                    self._json_response({'active': scan_pins()})
                    return

                # Static files (path-traversal safe)
                rel = path.lstrip('/')
                full = os.path.realpath(os.path.join(_STATIC_DIR, rel))
                safe = os.path.realpath(_STATIC_DIR)
                if full.startswith(safe + os.sep) and os.path.isfile(full):
                    ext = os.path.splitext(full)[1]
                    self._serve_file(full, _MIME.get(ext, 'application/octet-stream'))
                    return

                self.send_error(404)

            def do_POST(self):
                path = urlparse(self.path).path
                length = int(self.headers.get('Content-Length', 0))
                raw = self.rfile.read(length) if length else b''

                if path == '/api/config':
                    try:
                        data = json.loads(raw) if raw else {}
                        update_config(data)
                        self._json_response({'ok': True})
                    except (json.JSONDecodeError, ValueError) as exc:
                        self._json_response({'error': str(exc)}, 400)
                    return

                if path == '/api/send':
                    try:
                        data = json.loads(raw) if raw else {}
                        text = str(data.get('text', ''))
                        if text:
                            send_text(text)
                        else:
                            stop_send()
                        self._json_response({'ok': True})
                    except (json.JSONDecodeError, ValueError) as exc:
                        self._json_response({'error': str(exc)}, 400)
                    return

                if path == '/api/test':
                    test_tone()
                    self._json_response({'ok': True})
                    return

                self.send_error(404)

        return Handler
