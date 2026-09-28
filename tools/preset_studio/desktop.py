"""Own the local server for exactly the lifetime of a dedicated app window."""
import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import threading

from service import Studio, make_server


def run_window(server, command):
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        subprocess.run(command, check=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8791)
    options = parser.parse_args()
    candidates = [Path(os.environ.get(root, '')) / suffix
                  for root in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')
                  for suffix in ('Google/Chrome/Application/chrome.exe',
                                 'Microsoft/Edge/Application/msedge.exe')]
    browser = next((path for path in candidates if path.is_file()), None)
    if browser is None:
        raise RuntimeError('Preset Studio needs Chrome or Edge installed.')
    studio = Studio(options.runtime)
    server = make_server(studio, options.port)
    command = [str(browser), f'--app=http://127.0.0.1:{server.server_port}/',
               f'--user-data-dir={studio.root / "browser-profile"}',
               '--no-first-run', '--no-default-browser-check',
               '--disable-background-mode', '--disable-extensions']
    run_window(server, command)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), 'Preset Studio', 0x10)
