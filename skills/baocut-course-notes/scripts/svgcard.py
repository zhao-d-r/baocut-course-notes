#!/usr/bin/env python3
"""Explainer cards that follow references/layered-reading.md: 400-wide, text >= 16, page palette, UTF-8.

  build  --spec card.json --out visuals/s01.svg   rows of boxes, top to bottom, arrows between rows
  lint   visuals/*.svg                              check hand-written SVGs against the same rules

Spec: {"title": "...", "rows": [ROW, ...]} where ROW is a box or a list of two boxes (two columns).
Box: {"label": "...", "text": "...", "tone": "plain|green|red|purple|note", "tag": "§3"}.
Cards only lay out what the full notes already say; refs still go in notes.json visual.refs.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

from course_notes import dump, safe_path, write

W, PAD, GAP = 400, 10, 34
FONT = 'PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif'
INK, MUTED, LINE = '#242b29', '#636c66', '#dcded4'
TONES = {'plain': ('#faf8f3', INK, LINE), 'green': ('#e6efe8', '#244e3d', '#e6efe8'),
         'red': ('#f6e8e1', '#974c35', '#f6e8e1'), 'purple': ('#efeaf4', '#5a4775', '#efeaf4'),
         'note': ('#ffffff', MUTED, LINE)}


def width(text, size):
    return sum(size if ord(ch) > 0x2E7F else size * 0.56 for ch in text)


def wrap(text, size, limit):
    lines, line = [], ''
    for ch in text:
        if ch == '\n' or (line and width(line + ch, size) > limit):
            lines.append(line)
            line = '' if ch == '\n' else ch
        else:
            line += ch
    return lines + ([line] if line else [])


def box(spec, x, w):
    """Return (svg fragment builder, height) for one box at column x of width w."""
    fill, accent, stroke = TONES.get(spec.get('tone', 'plain'), TONES['plain'])
    label = wrap(spec.get('label', ''), 20, w - 40)
    body = wrap(spec.get('text', ''), 18, w - 40)
    h = 24 + 28 * len(label) + 26 * len(body) + (8 if label and body else 0)

    def draw(y, row_h):
        out = [f'<rect x="{x}" y="{y}" width="{w}" height="{row_h}" rx="12" fill="{fill}" stroke="{stroke}"/>']
        ty = y + 18
        for line in label:
            ty += 26
            out.append(f'<text x="{x + 20}" y="{ty}" font-size="20" font-weight="700" fill="{accent}">{html.escape(line)}</text>')
        if spec.get('tag'):
            out.append(f'<text x="{x + w - 16}" y="{y + 44}" font-size="16" fill="{MUTED}" text-anchor="end">{html.escape(spec["tag"])}</text>')
        ty += 8 if label and body else 0
        for line in body:
            ty += 26
            out.append(f'<text x="{x + 20}" y="{ty}" font-size="18" fill="{INK}">{html.escape(line)}</text>')
        return out
    return draw, h


def build_svg(spec):
    title = spec.get('title')
    if not isinstance(title, str) or not title.strip():
        raise ValueError('Card needs a title (used as accessible name)')
    rows = spec.get('rows')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Card needs rows')
    parts, y = [], PAD
    for n, row in enumerate(rows):
        cells = row if isinstance(row, list) else [row]
        if len(cells) not in (1, 2) or any(not isinstance(c, dict) for c in cells):
            raise ValueError(f'Row {n} must be one box or a list of two boxes')
        cw = (W - 2 * PAD - 10) // 2 if len(cells) == 2 else W - 2 * PAD
        drawn = [box(c, PAD + k * (cw + 10), cw) for k, c in enumerate(cells)]
        h = max(d[1] for d in drawn)
        if n:
            for k in range(len(cells)):
                cx = PAD + k * (cw + 10) + cw // 2
                parts.append(f'<path d="M{cx} {y - GAP + 4} L{cx} {y - 6}" stroke="{MUTED}" stroke-width="3" fill="none" marker-end="url(#a)"/>')
        for draw, _ in drawn:
            parts.extend(draw(y, h))
        y += h + GAP
    height = y - GAP + PAD
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" font-family="{FONT}" role="img">'
            f'<title>{html.escape(title)}</title><defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
            f'markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{MUTED}"/></marker></defs>')
    return head + ''.join(parts) + '</svg>\n'


def lint_svg(path):
    problems = []
    data = Path(path).read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        return [f'not UTF-8 (byte {exc.start})']
    m = re.search(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', text)
    if not m:
        problems.append('missing viewBox')
    elif float(m[1]) > 420:
        problems.append(f'viewBox width {m[1]} > 400: text shrinks below 13px on phones')
    small = sorted({float(s) for s in re.findall(r'font-size="([\d.]+)', text) if float(s) < 16})
    if small:
        problems.append(f'font-size below 16: {small}')
    if re.search(r'<(script|image|foreignObject)\b|xlink:href="http|href="http|@import', text):
        problems.append('external reference, script or embedded image')
    if '<title>' not in text:
        problems.append('missing <title> accessible name')
    return problems


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build'); b.add_argument('--spec', required=True); b.add_argument('--out', required=True)
    lt = sub.add_parser('lint'); lt.add_argument('paths', nargs='+')
    args = p.parse_args()
    try:
        if args.command == 'build':
            spec = json.loads(safe_path(args.spec).read_text(encoding='utf-8'))
            write(args.out, build_svg(spec))
            print(dump({'output': str(safe_path(args.out)), 'lint': lint_svg(safe_path(args.out))}))
        else:
            report = {str(path): lint_svg(path) for path in args.paths}
            print(dump({'status': 'failed' if any(report.values()) else 'passed', 'files': report}))
            if any(report.values()):
                sys.exit(1)
    except (ValueError, KeyError, OSError) as exc:
        p.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
