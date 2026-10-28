#!/usr/bin/env python3
"""Find and fetch official slides and readings from a course page.

  links <url> [--match WORD ...]   every link on the page, in its same-origin scripts and in linked Google Docs,
                                   with the text around it; links near a --match word come first
  fetch <url> --out DIR            download one file; Google Drive/Docs/Slides links become their export URL
  pdf <file> --out DIR [--render 3,5-7]
                                   pages.txt with every physical page's text under [page N] markers, and JPEG
                                   renders of the listed pages (pdf_page images for the notes); needs PyMuPDF

Course sites often render their schedule with JavaScript, so a slides link may exist only inside a script bundle,
and a Google Doc's plain-text export drops its hyperlinks. Reading the page as text misses both; this does not.
Uses plain requests only: no login, no bot-check workarounds. A page that refuses them is reported, not retried.
"""
import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

LIMIT = 5_000_000  # bytes read per page or script
FILE_LIMIT = 300_000_000  # bytes per downloaded file
URL = re.compile(r'https?://[^\s"\'`<>\\)\]]+')
HREF = re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
SCRIPT = re.compile(r'<script\b[^>]*?src\s*=\s*["\']([^"\']+)["\']', re.I)
DOC = re.compile(r'https://docs\.google\.com/(document|presentation|spreadsheets)/d/([\w-]+)')
DRIVE = re.compile(r'https://drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:export=download&)?id=)([\w-]+)')


def get(url, limit=LIMIT):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
        return r.read(limit), r.headers.get_content_type(), r.geturl(), r.headers.get_filename()


def kind(url, text=''):
    s = (url + ' ' + text).lower()
    if DOC.match(url) and '/presentation/' in url or 'slide' in s:
        return 'slides'
    if url.lower().split('?')[0].endswith('.pdf') or DRIVE.match(url):
        return 'pdf_or_drive_file'
    if DOC.match(url):
        return 'google_doc'
    if any(k in s for k in ('youtube.com', 'youtu.be', 'bilibili.com', 'vimeo.com')):
        return 'video'
    if any(k in s for k in ('arxiv.org', 'doi.org', 'openreview', 'acm.org', 'paper')):
        return 'paper'
    return 'other'


def plain(fragment):
    return re.sub(r'\s+', ' ', htmllib.unescape(re.sub(r'<[^>]+>', ' ', fragment))).strip()


def scan(text, base, source, is_html):
    """Links in one document: anchors with their text in HTML, every absolute URL with surrounding text otherwise."""
    rows = []
    if is_html:
        for m in HREF.finditer(text):
            url = urllib.parse.urljoin(base, htmllib.unescape(m[1]))
            if url.startswith('http'):
                before = plain(text[max(0, m.start() - 300):m.start()])[-120:]
                rows.append({'url': url, 'text': plain(m[2])[:200], 'context': before, 'source': source})
    for m in URL.finditer(text):
        url = htmllib.unescape(m[0]).rstrip('.,;')
        if any(r['url'] == url for r in rows):
            continue
        rows.append({'url': url, 'text': '', 'context': plain(text[max(0, m.start() - 160):m.end() + 80])[:300], 'source': source})
    return rows


def doc_export(url):
    m = DOC.match(url)
    if not m:
        return None
    fmt = {'document': 'html', 'presentation': 'pdf', 'spreadsheets': 'csv'}[m[1]]
    return f'https://docs.google.com/{m[1]}/d/{m[2]}/export?format={fmt}'


def links(args):
    rows, problems, seen = [], [], set()

    def visit(url, source, depth):
        target = doc_export(url) if DOC.match(url) and '/document/' in url else url
        if target in seen:
            return
        seen.add(target)
        try:
            body, ctype, final, _ = get(target)
        except OSError as exc:
            problems.append(f'{url}: {exc}')
            return
        text = body.decode('utf-8', 'replace')
        is_html = 'html' in ctype
        found = scan(text, final, source, is_html)
        rows.extend(found)
        if depth:
            return
        origin = urllib.parse.urlsplit(final).netloc
        for src in SCRIPT.findall(text) if is_html else []:
            js = urllib.parse.urljoin(final, src)
            if urllib.parse.urlsplit(js).netloc == origin:
                visit(js, f'script {urllib.parse.urlsplit(js).path}', 1)
        for r in found:
            if DOC.match(r['url']) and '/document/' in r['url']:
                visit(r['url'], f"linked doc {r['url']}", 1)

    visit(args.url, 'page', 0)
    unique = {}
    for r in rows:
        if r['url'] not in unique and not r['url'].endswith(('.js', '.css', '.woff2', '.png', '.svg', '.ico')):
            unique[r['url']] = dict(r, kind=kind(r['url'], r['text'] + ' ' + r['context'][-60:]))
    words = [w.lower() for w in args.match or []]
    hit = lambda r: any(w in (r['text'] + ' ' + r['context']).lower() for w in words)
    out = sorted(unique.values(), key=lambda r: (not hit(r), r['kind'] == 'other'))
    for r in out:
        r['match'] = hit(r)
    print(json.dumps({'url': args.url, 'documents_read': sorted(seen), 'links': out, 'problems': problems,
                      'next': 'Open the candidates near this lecture (match=true first); register what you use or rule out in materials.json'},
                     ensure_ascii=False, indent=2))


def fetch(args):
    url = args.url
    m = DRIVE.match(url)
    target = f'https://drive.google.com/uc?export=download&id={m[1]}' if m else (doc_export(url) or url)
    body, ctype, final, filename = get(target, FILE_LIMIT)
    if 'html' in ctype and not url.endswith(('.html', '.htm')) and (m or DOC.match(url)):
        raise ValueError(f'{final} returned a web page, not the file (private, too large or needs sign-in); open it in a browser instead')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = Path(args.name or filename or urllib.parse.urlsplit(final).path).name or 'download'
    if body[:5] == b'%PDF-' and not name.lower().endswith('.pdf'):
        name += '.pdf'
    elif '.' not in name:
        name += {'application/pdf': '.pdf', 'text/html': '.html', 'text/csv': '.csv'}.get(ctype, '')
    path = out / name
    path.write_bytes(body)
    print(json.dumps({'url': url, 'fetched': target, 'path': str(path), 'content_type': ctype, 'bytes': len(body),
                      'truncated': len(body) >= FILE_LIMIT, 'sha256': hashlib.sha256(body).hexdigest()}, indent=2))


def page_list(spec, total):
    pages = set()
    for part in filter(None, (spec or '').split(',')):
        a, _, b = part.partition('-')
        pages.update(range(int(a), int(b or a) + 1))
    bad = sorted(n for n in pages if not 1 <= n <= total)
    if bad:
        raise ValueError(f'pages {bad} are outside 1-{total}')
    return sorted(pages)


def pdf(args):
    try:
        import pymupdf
    except ImportError:
        raise ValueError('PyMuPDF is missing. Install it next to the run, then rerun with it on the path:\n'
                         '  python3 -m pip install --target <run>/.deps pymupdf\n'
                         '  PYTHONPATH=<run>/.deps python3 materials.py pdf ...') from None
    doc = pymupdf.open(args.file)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text = ''.join(f'[page {i}]\n{page.get_text()}\n' for i, page in enumerate(doc, 1))
    (out / 'pages.txt').write_text(text, encoding='utf-8')
    images = []
    for n in page_list(args.render, len(doc)):
        path = out / f'page-{n:03d}.jpg'
        doc[n - 1].get_pixmap(dpi=args.dpi).save(str(path), jpg_quality=85)
        images.append(str(path))
    print(json.dumps({'file': args.file, 'pages': len(doc), 'text': str(out / 'pages.txt'), 'images': images,
                      'empty_text_pages': [i for i, page in enumerate(doc, 1) if not page.get_text().strip()],
                      'note': 'Pages without text are images or scans: look at their renders instead of trusting pages.txt'}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    lk = sub.add_parser('links'); lk.add_argument('url'); lk.add_argument('--match', nargs='*', help='lecture title, speaker, date')
    ft = sub.add_parser('fetch'); ft.add_argument('url'); ft.add_argument('--out', required=True); ft.add_argument('--name')
    pd = sub.add_parser('pdf'); pd.add_argument('file'); pd.add_argument('--out', required=True)
    pd.add_argument('--render', help='physical pages to render as JPEG, e.g. 3,5-7'); pd.add_argument('--dpi', type=int, default=150)
    args = parser.parse_args()
    try:
        {'links': links, 'fetch': fetch, 'pdf': pdf}[args.command](args)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
