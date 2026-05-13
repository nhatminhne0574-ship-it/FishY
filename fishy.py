#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import shutil
import threading

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

# Add pip user site-packages for playwright
user_site = os.path.expanduser('~/.local/lib/python3.13/site-packages')
if os.path.isdir(user_site):
    sys.path.insert(0, user_site)

from app import app, cleanup, find_free_port


def check_dependencies():
    missing = []
    if not shutil.which('wget'):
        missing.append('wget')
    try:
        import flask
    except ImportError:
        missing.append('flask')
    try:
        import webview
    except ImportError:
        missing.append('pywebview')
    return missing


def print_banner():
    print('''
  \033[38;5;141m╔══════════════════════════════════════════╗
  ║         \033[38;5;050m🐟  FishY\033[38;5;141m  v1.0              ║
  ║     Phish Any Page — Pentest Tool          ║
  ╚══════════════════════════════════════════╝\033[0m

  \033[38;5;244mClose the window to stop and clean up.\033[0m
''')


def main():
    import webview

    missing = check_dependencies()
    if missing:
        print(f'\n  \033[38;5;196mMissing: {", ".join(missing)}\033[0m')
        input('  Press Enter to exit...')
        sys.exit(1)

    print_banner()

    port = find_free_port()
    url = f'http://127.0.0.1:{port}'

    server_thread = threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=port, debug=False, threaded=True),
        daemon=True
    )
    server_thread.start()
    time.sleep(1.5)

    window = webview.create_window(
        'FishY — Phish Any Page',
        url=url,
        width=880,
        height=680,
        resizable=True,
        min_size=(660, 480),
        text_select=True,
        easy_drag=False,
    )

    webview.start(private_mode=True, debug=False)

    print('  \033[38;5;050m🧹 Cleaning up...\033[0m')
    cleanup()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        print(f'  \033[38;5;196mError: {e}\033[0m')
        cleanup()
