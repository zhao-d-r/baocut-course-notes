#!/usr/bin/env python3
"""Turn a text model's code into a checked PNG explainer: no image model, no image quota, no misspelt words.

  render.py antv --dsl s3.infographic --labels-json labels.json --out raw-s3.png [--width 800 --height 1200]
      AntV Infographic syntax (structured: steps, comparisons, hierarchies, timelines, cycles; icons)
  render.py page --html draw-s3.html --labels-json labels.json --out raw-s3.png [--width 1024 --height 1536]
      freeform HTML + rough.js hand-drawn kit (assets/freeform.html), for anything the templates don't fit

labels.json is the list of every phrase the picture may show. Both modes render in headless Chrome, run the
same check (every text is a label; nothing off-canvas; no overlapping text; freeform: no stroke through text),
crop to the content, and print JSON. Exit 1 when the check finds problems: fix the source and run again.
"""
import argparse
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
CHROMES = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
           '/Applications/Chromium.app/Contents/MacOS/Chromium', 'google-chrome', 'chromium', 'chromium-browser']


def chrome():
    for c in [os.environ.get('CHROME', '')] + CHROMES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    raise ValueError('Chrome/Chromium not found; set CHROME=/path/to/chrome')


def asset(name):
    return (ASSETS / name).read_text(encoding='utf-8')


def inline(js):
    return '<script>' + js.replace('</script', '<\\/script') + '</script>'


def render(page, labels, w, h, scale, out, margin):
    """Inject the kit, render next to `out` (so relative files resolve), check, screenshot, crop."""
    head = (f'<style>:root{{--w:{w}px;--h:{h}px}}</style>' + inline(asset('rough.js'))
            + inline(f'window.__W={w};window.__H={h};window.__LABELS={json.dumps(labels, ensure_ascii=False)};')
            + inline(asset('kit.js')))
    page = re.sub(r'(<head[^>]*>)', lambda m: m.group(1) + head, page, count=1) if '<head' in page else head + page
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.render-', suffix='.html', dir=out.parent)
    os.close(fd)
    tmp, raw = Path(tmp), out.with_name('.render-full-' + out.name)
    try:
        tmp.write_text(page, encoding='utf-8')
        base = [chrome(), '--headless=new', '--disable-gpu', '--hide-scrollbars', '--allow-file-access-from-files',
                f'--window-size={w},{h}', f'--force-device-scale-factor={scale}', '--virtual-time-budget=20000']
        dom = subprocess.run(base + ['--dump-dom', tmp.as_uri()], capture_output=True, text=True, timeout=180).stdout
        m = re.search(r'<pre id="__check"[^>]*>(.*?)</pre>', dom, re.S)
        result = json.loads(htmllib.unescape(m.group(1))) if m else {
            'problems': ['checker did not run (page script error, or the page has no <body>)'], 'warnings': [], 'box': None}
        subprocess.run(base + [f'--screenshot={raw}', tmp.as_uri()], capture_output=True, text=True, timeout=180)
        if not raw.exists():
            raise ValueError('Chrome wrote no screenshot')
        box = result.pop('box', None)
        if box and shutil.which('ffmpeg'):
            x, y = max(0, box['x'] - margin), max(0, box['y'] - margin)
            cw, ch = min(w - x, box['w'] + 2 * margin), min(h - y, box['h'] + 2 * margin)
            crop = f'crop={int(cw * scale)}:{int(ch * scale)}:{int(x * scale)}:{int(y * scale)}'
            r = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(raw), '-vf', crop, str(out)],
                               capture_output=True, text=True)
            if r.returncode:
                shutil.copyfile(raw, out)
        else:
            shutil.copyfile(raw, out)
    finally:
        tmp.unlink(missing_ok=True)
        raw.unlink(missing_ok=True)
    return result


def labels_of(args):
    labels = json.loads(Path(args.labels_json).read_text(encoding='utf-8')) if args.labels_json else []
    labels += args.label or []
    if not labels:
        raise ValueError('Give the allowed words: --labels-json file.json (a list of phrases) or --label ... (repeatable)')
    return labels


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='mode', required=True)
    for name, src, w, h, scale in (('antv', '--dsl', 800, 1200, 2), ('page', '--html', 1024, 1536, 1)):
        s = sub.add_parser(name)
        s.add_argument(src, dest='src', required=True)
        s.add_argument('--labels-json'); s.add_argument('--label', action='append')
        s.add_argument('--out', required=True)
        s.add_argument('--width', type=int, default=w); s.add_argument('--height', type=int, default=h)
        s.add_argument('--scale', type=float, default=scale, help='device pixel ratio of the PNG')
        s.add_argument('--margin', type=int, default=40, help='px kept around the content when cropping')
    args = p.parse_args()
    try:
        labels = labels_of(args)
        src = Path(args.src).expanduser().resolve()
        text = src.read_text(encoding='utf-8')
        if args.mode == 'antv':
            text = (asset('antv.html').replace('<script src="antv-infographic.min.js"></script>', inline(asset('antv-infographic.min.js')))
                    .replace('{{DSL}}', json.dumps(text.strip(), ensure_ascii=False).replace('</', '<\\/')))
        out = Path(args.out).expanduser().resolve()
        result = render(text, labels, args.width, args.height, args.scale, out, args.margin)
    except (ValueError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        p.exit(1, f'Error: {exc}\n')
    print(json.dumps({'output': str(out), 'mode': args.mode, **result}, ensure_ascii=False, indent=2))
    if result['problems']:
        print(f"{len(result['problems'])} problem(s); fix the source and render again", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
