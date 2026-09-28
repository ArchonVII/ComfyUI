import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import run_window


class DesktopLifecycleTests(unittest.TestCase):
    def test_server_lives_only_until_window_exits(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        address = f'http://127.0.0.1:{server.server_port}'
        def window(*args, **kwargs):
            self.assertEqual(urllib.request.urlopen(address, timeout=2).status, 200)
        with patch('desktop.subprocess.run', side_effect=window):
            run_window(server, ['browser'])
        self.assertEqual(server.fileno(), -1)

    def test_failed_browser_launch_also_closes_server(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
        with patch('desktop.subprocess.run', side_effect=OSError('launch failed')):
            with self.assertRaises(OSError):
                run_window(server, ['missing-browser'])
        self.assertEqual(server.fileno(), -1)
