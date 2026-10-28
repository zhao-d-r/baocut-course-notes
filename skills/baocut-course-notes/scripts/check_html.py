#!/usr/bin/env python3
"""Delivery checks for a rendered notes page, in one command.

  check_html.py <run>/课堂笔记.html [--out-dir <run>/qa] [--chrome PATH] [--no-browser]

Static checks always run: internal anchors and local links resolve, no external resources,
embedded images decode, layered controls exist. If headless Chrome/Chromium is found, the page
is also loaded at 390 and 1280 px: horizontal overflow, script errors, broken images, mode
switch and "expand all" are exercised, and a screenshot is saved per width. Without a browser
the result says so (status static_only) instead of improvising other tools.
Writes <out-dir>/html-check.json and records status.browser_check in manifest.json if present.
"""
import argparse
import base64
import binascii
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from course_notes import dump, log_stage, safe_path, write

WIDTHS = ((390, 844), (1280, 900))
CHROMES = ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
           '/Applications/Chromium.app/Contents/MacOS/Chromium',
           '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge')
PROBE_HEAD = ("<script>window.__errs=[];addEventListener('error',e=>__errs.push(String(e.message||e)));"
              "(c=>{console.error=(...a)=>{__errs.push(a.join(' '));c(...a)}})(console.error.bind(console));</script>")
PROBE_TAIL = """<script>addEventListener('load',()=>setTimeout(()=>{const d=document.documentElement,r={width:innerWidth,scroll_width:d.scrollWidth};
r.overflow=d.scrollWidth>innerWidth+1;r.broken_images=[...document.images].filter(i=>i.getAttribute('src')&&i.complete&&i.naturalWidth===0).map(i=>(i.alt||'').slice(0,60)).slice(0,10);
const modes=[...document.querySelectorAll('[data-mode]')];r.modes=modes.map(b=>b.dataset.mode);
try{modes.forEach(b=>b.click());document.querySelectorAll('details').forEach(x=>x.open=true);r.interaction='ok'}catch(e){r.interaction=String(e)}
r.overflow_expanded=d.scrollWidth>innerWidth+1;r.errors=__errs.slice(0,20);
const host=parent!==window?parent.document:document,p=host.createElement('pre');p.id='__probe';p.textContent=JSON.stringify(r);host.body.appendChild(p)},1200));</script>"""
# Headless Chrome will not size a window below ~500px, so phone widths load the page in an iframe of that width.
FRAME = '<!doctype html><meta charset="utf-8"><body style="margin:0"><iframe src="probe.html" style="width:{w}px;height:{h}px;border:0"></iframe></body>'


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.anchors, self.links, self.external, self.images, self.classes = set(), [], [], [], [], {}
        self.modes = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'):
            self.ids.add(a['id'])
        for c in (a.get('class') or '').split():
            self.classes[(tag, c)] = self.classes.get((tag, c), 0) + 1
        if a.get('data-mode'):
            self.modes.append(a['data-mode'])
        href = a.get('href')
        if tag == 'a' and href:
            if href.startswith('#'):
                if len(href) > 1:
                    self.anchors.append(href[1:])
            elif not re.match(r'^(https?:|mailto:|data:)', href):
                self.links.append(href.split('#')[0])
        src = a.get('src') if tag in ('img', 'script', 'iframe', 'source') else a.get('href') if tag == 'link' else None
        if src:
            if re.match(r'^(https?:)?//', src):
                self.external.append(f'{tag} {src[:80]}')
            elif tag == 'img':
                self.images.append(src)


def static_checks(page, html_dir):
    s = Scan()
    s.feed(page)
    problems = []
    missing = sorted(set(x for x in s.anchors if x not in s.ids))
    if missing:
        problems.append(f'{len(missing)} internal anchors point nowhere: {missing[:8]}')
    gone = sorted(set(x for x in s.links if x and not (html_dir / x).exists()))
    if gone:
        problems.append(f'local links to missing files (ship them next to the page): {gone[:8]}')
    if s.external:
        problems.append(f'external resources break offline reading: {s.external[:5]}')
    bad = 0
    for src in s.images:
        m = re.match(r'data:image/[\w+.-]+;base64,(.*)', src, re.S)
        if not m:
            bad += 1
            continue
        try:
            base64.b64decode(m[1][:4000] + '=' * (-len(m[1][:4000]) % 4), validate=True)
        except (binascii.Error, ValueError):
            bad += 1
    if bad:
        problems.append(f'{bad} images are not embedded data URIs or do not decode')
    cards = s.classes.get(('section', 'card'), 0)
    layered = cards > 0
    if layered:
        if not {'visual', 'full'} <= set(s.modes):
            problems.append('layered page lacks the visual/full mode switch')
        deep = s.classes.get(('details', 'deep'), 0)
        if deep != cards:
            problems.append(f'{cards} section cards but {deep} expandable full-note blocks')
    return {'sections': cards, 'images': len(s.images), 'explainers': s.classes.get(('figure', 'explainer'), 0),
            'internal_anchors': len(s.anchors), 'problems': problems}


def find_chrome(explicit):
    for c in (explicit, os.environ.get('CHROME'), *map(shutil.which, ('google-chrome', 'chromium', 'chromium-browser', 'chrome')), *CHROMES):
        if c and Path(c).exists():
            return c
    return None


def browser_checks(page, chrome, out_dir):
    probe = page.replace('loading="lazy"', 'loading="eager"')
    probe = re.sub(r'<head[^>]*>', lambda m: m[0] + PROBE_HEAD, probe, count=1)
    probe = probe.replace('</body>', PROBE_TAIL + '</body>') if '</body>' in probe else probe + PROBE_TAIL
    results, problems = {}, []
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'probe.html').write_text(probe, encoding='utf-8')
        base = [chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
                '--allow-file-access-from-files', f'--user-data-dir={tmp}/profile', '--virtual-time-budget=15000']
        for w, h in WIDTHS:
            f = Path(tmp) / 'probe.html'
            if w < 500:
                f = Path(tmp) / f'frame-{w}.html'
                f.write_text(FRAME.format(w=w, h=h), encoding='utf-8')
            dom = subprocess.run(base + [f'--window-size={max(w, 500)},{h}', '--dump-dom', f.as_uri()], capture_output=True, text=True, timeout=120)
            m = re.search(r'<pre id="__probe">(.*?)</pre>', dom.stdout, re.S)
            if not m:
                problems.append(f'{w}px: page did not finish loading in headless Chrome')
                continue
            r = json.loads(m[1].replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&'))
            shot = out_dir / f'shot-{w}.png'
            subprocess.run(base + [f'--window-size={max(w, 500)},{h}', f'--screenshot={shot}', f.as_uri()],
                           capture_output=True, timeout=120)
            r['screenshot'] = shot.name if shot.exists() else None
            results[str(w)] = r
            for key, msg in (('overflow', 'horizontal overflow'), ('overflow_expanded', 'horizontal overflow after expanding all')):
                if r.get(key):
                    problems.append(f'{w}px: {msg} (scroll width {r["scroll_width"]})')
            if r.get('errors'):
                problems.append(f'{w}px: script errors {r["errors"][:3]}')
            if r.get('broken_images'):
                problems.append(f'{w}px: broken images {r["broken_images"][:3]}')
            if r.get('interaction') != 'ok':
                problems.append(f'{w}px: interaction failed: {r.get("interaction")}')
    return results, problems


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('html'); p.add_argument('--out-dir'); p.add_argument('--chrome'); p.add_argument('--no-browser', action='store_true')
    args = p.parse_args()
    try:
        html_path = safe_path(args.html)
        out_dir = safe_path(args.out_dir) if args.out_dir else html_path.parent / 'qa'
        out_dir.mkdir(parents=True, exist_ok=True)
        page = html_path.read_text(encoding='utf-8')
        static = static_checks(page, html_path.parent)
        chrome = None if args.no_browser else find_chrome(args.chrome)
        browser, b_problems = browser_checks(page, chrome, out_dir) if chrome else ({}, [])
        problems = static['problems'] + b_problems
        status = 'failed' if problems else ('passed' if chrome else 'static_only')
        report = {'html': str(html_path), 'status': status, 'browser': chrome or 'unavailable: interaction not tested',
                  'static': static, 'widths': browser, 'problems': problems,
                  'scope': 'Emulated widths in headless Chrome, not a real phone; reading quality still needs a human look.'}
        write(out_dir / 'html-check.json', dump(report) + '\n')
        summary = f'{status}: ' + ('; '.join(problems[:3]) if problems else
                                   ('390/1280px headless Chrome, modes + expand-all exercised, no overflow or script errors' if chrome else 'static checks only; no browser available'))
        manifest = html_path.parent / 'manifest.json'
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if not (data.get('revisions') or [{}])[-1].get('delivered'):  # never rewrite a delivered archive
                data.setdefault('status', {})['browser_check'] = summary
                write(manifest, dump(data) + '\n')
        log_stage(html_path.parent, 'browser_check', 'failed' if problems else 'completed', summary, str(out_dir / 'html-check.json'))
        print(dump(report))
        sys.exit(1 if problems else 0)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        p.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
