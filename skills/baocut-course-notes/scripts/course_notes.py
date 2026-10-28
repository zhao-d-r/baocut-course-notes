#!/usr/bin/env python3
"""Deterministic handoff helpers. No model calls and no .bcut writes."""
import argparse
import base64
import hashlib
import html
import json
import math
import os
from pathlib import Path
import tempfile


def safe_path(value):
    p = Path(value).expanduser().resolve()
    if any(x.endswith('.bcut') for x in p.parts):
        raise ValueError('Use exported copies outside .bcut; project operations belong to BaoCut CLI')
    return p


def read_json(path):
    return json.loads(safe_path(path).read_text(encoding='utf-8'))


def write(path, data):
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=p.parent, delete=False) as f:
        tmp = f.name
        f.write(data)
    os.replace(tmp, p)


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def seconds(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0:
        raise ValueError('Time must be a finite nonnegative number')
    return x


PLACEHOLDER = 'TODO(scaffold)'


class Problems(list):
    """Collects every validation failure with a field path instead of stopping at the first."""

    def attempt(self, where, fn, *args):
        try:
            return fn(*args)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.append((where, exc))

    def report(self):
        return [{'where': w, 'error': ('missing field ' + str(e)) if isinstance(e, KeyError) else str(e)} for w, e in self]


def log_stage(run_dir, stage, status, detail='', evidence=None):
    """Append to run manifest.json when one exists; scripts log their own stages so agents need not."""
    path = Path(run_dir) / 'manifest.json'
    if not path.exists():
        return
    import datetime as dt
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data.get('revisions') or [{}])[-1].get('delivered'):
        return  # a delivered run is an archive: re-checking it must not rewrite its manifest
    data.setdefault('log', []).append({'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'occurred_at': None, 'stage': stage,
                                       'status': status, 'attempt': None, 'job_id': None, 'detail': detail, 'evidence': evidence})
    write(path, dump(data) + '\n')


def chunks(args):
    src = safe_path(args.input)
    out = safe_path(args.out)
    data = read_json(src)
    rows = data.get('sentences') or data.get('segments')  # older bcut-cli exports vs BaoCut 3.x transcript JSON
    if not rows:
        raise ValueError('Expected nonempty BaoCut export sentences or segments')
    seen, normalized = set(), []
    for r in rows:
        ident = r['id']
        if ident in seen or not isinstance(ident, str):
            raise ValueError('Sentence IDs must be unique strings')
        seen.add(ident)
        start, end = seconds(r['start']), seconds(r['end'])
        if end < start or not isinstance(r['text'], str):
            raise ValueError('Invalid sentence')
        normalized.append(dict(id=ident, start=start, end=end, text=r['text']))
    normalized.sort(key=lambda r: (r['start'], r['end']))
    groups, group, chars = [], [], 0
    for row in normalized:
        if group and (row['start'] - group[0]['start'] >= 300 or chars + len(row['text']) > 6000):
            groups.append(group)
            group, chars = [], 0
        group.append(row)
        chars += len(row['text'])
    if group:
        groups.append(group)
    index = {'version': 1, 'source_sha256': hashlib.sha256(src.read_bytes()).hexdigest(), 'chunks': [], 'sentences': []}
    for i, group in enumerate(groups, 1):
        ident = f'chunk-{i:04d}'
        write(out / (ident + '.json'), dump(group))
        index['chunks'].append({'id': ident, 'file': ident + '.json', 'start': group[0]['start'], 'end': max(r['end'] for r in group), 'source_ids': [r['id'] for r in group]})
        index['sentences'].extend({k: r[k] for k in ('id', 'start', 'end')} for r in group)
    write(out / 'index.json', dump(index))
    print(dump({'index': str(out / 'index.json'), 'chunks': len(groups), 'sentences': len(rows)}))


def esc(s):
    if not isinstance(s, str):
        raise ValueError('Expected plain text string')
    return html.escape(s, quote=True)


def stamp(t):
    t = int(t)
    return f'{t // 3600:02}:{t // 60 % 60:02}:{t % 60:02}'


def source_link(url, label):
    if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
        raise ValueError('Source URL must be http(s)')
    return f'<a href="{esc(url)}">{esc(label)}</a>'


def page_label(pages):
    if not pages or any(isinstance(p, bool) or not isinstance(p, int) or p < 1 for p in pages):
        raise ValueError('PDF pages must be positive physical page numbers')
    return 'PDF物理页 ' + '、'.join(str(p) for p in pages)


def figure_source(frame, run_dir, start, end):
    """Validate one notes frame; return (provenance HTML, data URI)."""
    kind = frame.get('source_type', 'video_frame')
    if kind == 'video_frame':
        t = seconds(frame['time'])
        if not start <= t <= end:
            raise ValueError('Screenshot outside section interval')
        origin = ('视频原帧 ' if frame.get('source_type') else '') + stamp(t)
    elif kind == 'pdf_page':
        if frame.get('time') is not None:
            raise ValueError('PDF image has no video capture time; use related_time for navigation')
        origin = esc(frame['source_label']) + ' · ' + page_label([frame['page']])
        if not frame['source_label'].strip():
            raise ValueError('PDF image requires source_label')
        if frame.get('source_url'):
            origin += ' · ' + source_link(frame['source_url'], '原始讲义')
        if frame.get('related_time') is not None:
            t = seconds(frame['related_time'])
            if not start <= t <= end:
                raise ValueError('Related lecture time outside section interval')
            origin += ' · 相关讲解 ' + stamp(t) + '（不是同秒视频截图）'
    else:
        raise ValueError('Unknown image source_type')
    path = safe_path(Path(run_dir) / frame['path'])
    if not path.is_relative_to(Path(run_dir).resolve()):
        raise ValueError('Screenshot must stay inside run directory')
    data = path.read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif data.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise ValueError('Expected PNG/JPEG/WebP screenshot')
    return origin, 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')


def text_of(item):
    """Content items are plain strings, or {"text", "caveat"} in notes v3."""
    if isinstance(item, dict):
        if set(item) - {'text', 'caveat'} or not isinstance(item.get('text'), str) or not isinstance(item.get('caveat', ''), str):
            raise ValueError('Content item object allows only text and caveat strings')
        return item['text']
    if not isinstance(item, str):
        raise ValueError('Expected plain text string')
    return item


def placeholders(obj, where, problems):
    """Scaffold markers left in notes.json mean a field was never written."""
    if isinstance(obj, str) and PLACEHOLDER in obj:
        problems.append((where, ValueError('Placeholder text remains; write this field from the transcript')))
    elif isinstance(obj, list):
        for j, v in enumerate(obj):
            placeholders(v, f'{where}[{j}]', problems)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            placeholders(v, f'{where}.{k}' if where else k, problems)


def section_html(s, i, expected, covered, note_path, problems):
    where = f'sections[{i-1}]'
    start, end = seconds(s['start']), seconds(s['end'])
    if end < start or not s.get('source_ids') or not s.get('paragraphs'):
        raise ValueError('Section requires interval, evidence IDs and prose')
    for ident in s['source_ids']:
        if ident not in expected:
            problems.append((f'{where}.source_ids', ValueError('Unknown evidence ID: ' + ident)))
        elif ident in covered:
            problems.append((f'{where}.source_ids', ValueError('Duplicate evidence assignment: ' + ident)))
        else:
            row = expected[ident]
            if row['start'] < start or row['end'] > end:
                problems.append((f'{where}.source_ids', ValueError('Section interval must contain its evidence: ' + ident)))
            covered.add(ident)
    title = esc(s['title'])
    block = f'<section id="s{i}"><small>{stamp(start)}—{stamp(end)}</small><h2>{title}</h2>'
    for j, p in enumerate(s['paragraphs']):
        block += '<p>' + (problems.attempt(f'{where}.paragraphs[{j}]', lambda: esc(text_of(p))) or '') + '</p>'
    for key, label in [('examples', '课堂案例与演示'), ('editor_notes', '整理者补充')]:
        if s.get(key):
            block += '<h3>' + label + '</h3>' + ''.join('<p>' + (problems.attempt(f'{where}.{key}[{j}]', lambda: esc(text_of(p))) or '') + '</p>' for j, p in enumerate(s[key]))
    images = 0
    for j, frame in enumerate(s.get('frames', [])):
        def one(frame=frame):
            origin, uri = figure_source(frame, note_path.parent, start, end)
            caption = esc(frame['caption'])
            if not caption.strip():
                raise ValueError('Screenshot needs caption')
            return f'<figure><button class="zoom" aria-label="放大：{caption}"><img src="{uri}" alt="{caption}" loading="eager"></button><figcaption>{origin} · {caption}</figcaption></figure>'
        fig = problems.attempt(f'{where}.frames[{j}]', one)
        if fig:
            block += fig
            images += 1
    return title, block + '</section>', images


def build(args, problems):
    """Validate notes and build the page, collecting every problem; returns (page, report)."""
    note_path = safe_path(args.notes)
    note, index = read_json(note_path), read_json(args.index)
    placeholders(note, '', problems)
    expected_chunks = {r['id'] for r in index['chunks']}
    if set(note.get('read_chunks', [])) != expected_chunks:
        problems.append(('read_chunks', ValueError('Reading ledger incomplete or contains unknown chunks')))
    expected = {r['id']: r for r in index['sentences']}
    covered, omitted = set(), set()
    for j, r in enumerate(note.get('omitted', [])):
        if r.get('id') not in expected or r['id'] in omitted or not r.get('reason', '').strip():
            problems.append((f'omitted[{j}]', ValueError('Invalid omission')))
        else:
            omitted.add(r['id'])
    parts, toc, image_count = [], [], 0
    sections = note.get('sections', [])
    if not sections:
        problems.append(('sections', ValueError('No note sections')))
    for i, s in enumerate(sections, 1):
        out = problems.attempt(f'sections[{i-1}]', section_html, s, i, expected, covered, note_path, problems)
        if out:
            title, block, images = out
            toc.append(f'<a href="#s{i}">{title}</a>')
            parts.append(block)
            image_count += images
    if sections and (covered & omitted or covered | omitted != set(expected)):
        missing = sorted(set(expected) - covered - omitted)
        detail = f' (unassigned: {", ".join(missing[:8])}{"…" if len(missing) > 8 else ""})' if missing else ''
        problems.append(('sections[].source_ids', ValueError('Evidence coverage missing or both used and omitted' + detail)))
    if note.get('summary'):
        body = ''.join('<p>' + (problems.attempt(f'summary[{j}]', esc, p) or '') + '</p>' for j, p in enumerate(note['summary']))
        parts.insert(0, '<section id="summary"><h2>先读摘要</h2>' + body + '</section>')
        toc.insert(0, '<a href="#summary">摘要</a>')
    if note.get('self_test'):
        body = ''
        for j, item in enumerate(note['self_test']):
            def quiz(item=item):
                link = ''
                if item.get('section') is not None:
                    n = item['section']
                    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(sections):
                        raise ValueError('Self-test section must reference an existing section')
                    link = f' <a href="#s{n}">回查第{n}节</a>'
                return '<h3>' + esc(item['question']) + '</h3><p>' + esc(item['answer']) + link + '</p>'
            body += problems.attempt(f'self_test[{j}]', quiz) or ''
        parts.append('<section id="self-test"><h2>自测（整理者补充）</h2>' + body + '</section>')
        toc.append('<a href="#self-test">自测</a>')
    supplements = note.get('supplements', [])
    if note.get('official_slide_supplements'):
        if supplements:
            problems.append(('supplements', ValueError('Use supplements or legacy official_slide_supplements, not both')))
        supplements = [dict(item, source_label=item.get('source_label', '官方讲义')) for item in note['official_slide_supplements']]
    if supplements:
        body = ''
        for j, item in enumerate(supplements):
            def supp(item=item):
                origin = esc(item['source_label'])
                if not item['source_label'].strip():
                    raise ValueError('Supplement requires source_label')
                if item.get('pages') is not None:
                    origin += ' · ' + page_label(item['pages'])
                if item.get('source_url'):
                    origin += ' · ' + source_link(item['source_url'], '原始资料')
                return '<h3>' + esc(item['title']) + '</h3><p>' + esc(item['text']) + '</p><p><small>' + origin + '</small></p>'
            body += problems.attempt(f'supplements[{j}]', supp) or ''
        parts.append('<section id="supplements"><h2>补充阅读（不计作课堂口述）</h2>' + body + '</section>')
        toc.append('<a href="#supplements">补充阅读</a>')
    url = note.get('source_url', '')
    if url and not url.startswith(('https://', 'http://')):
        problems.append(('source_url', ValueError('Source URL must be http(s)')))
        url = ''
    limits = note.get('limitations', [])
    if not limits:
        problems.append(('limitations', ValueError('State actual reading / visual verification scope in limitations')))
    counts = {'sections': len(sections), 'images': image_count, 'coverage_declared': len(covered), 'omitted': len(omitted)}
    if note.get('schema_version') == 3:
        if getattr(args, 'layout', None):
            problems.append(('--layout', ValueError('notes v3 carries its own layout; do not pass --layout')))
        import layered
        layered.validate(note, note_path.parent, problems)
        if problems:
            return None, counts
        page, report = layered.render(note, note_path.parent)
        return page, {'style': 'layered', **counts, 'visuals': report['visuals'], 'fidelity_eval': 'required: see references/fidelity-eval.md'}
    if problems:
        return None, counts
    template = Path(__file__).resolve().parents[1] / 'assets/template.html'
    page = template.read_text(encoding='utf-8')
    values = {'TITLE': esc(note['title']), 'META': f'{len(sections)} 节 · {image_count} 幅配图', 'TOC': ''.join(toc), 'BODY': ''.join(parts), 'LIMITS': ''.join('<p>' + esc(x) + '</p>' for x in limits), 'SOURCE': source_link(url, '回看原视频') if url else '来源为本地视频'}
    # One replacement pass: content resembling template markers stays literal.
    import re
    page = re.sub(r'\{\{(TITLE|META|TOC|BODY|LIMITS|SOURCE)\}\}', lambda m: values[m[1]], page)
    layout_path = getattr(args, 'layout', None)
    if layout_path is None and (note_path.parent / 'reading-layout.json').exists():
        layout_path = note_path.parent / 'reading-layout.json'
    if getattr(args, 'require_layout', False) and layout_path is None:
        raise ValueError('Editorial delivery requires reading-layout.json or --layout')
    if layout_path is not None:
        import reading_layout
        page, layout_report = reading_layout.render(note, read_json(layout_path), note_path.read_bytes(), page, template.parent)
    return page, {'style': 'editorial' if layout_path else 'legacy', **counts, 'semantic_and_browser_qa': 'required by agent'}


def render(args):
    problems = Problems()
    page, report = build(args, problems)
    if problems:
        raise problems[0][1]
    write(args.out, page)
    print(dump({'output': str(safe_path(args.out)), **report}))
    log_stage(safe_path(args.notes).parent, 'render', 'completed', f'{report["sections"]} sections', str(safe_path(args.out)))


def validate(args):
    """Report every problem at once, with field paths, without writing HTML."""
    problems = Problems()
    _, counts = build(args, problems)
    result = {'status': 'failed' if problems else 'passed', 'problems': problems.report(), **counts}
    print(dump(result))
    log_stage(safe_path(args.notes).parent, 'validate', 'failed' if problems else 'completed', f'{len(problems)} problems')
    return result


def scaffold(args):
    """Write a v3 skeleton bound to the chunk index; every prose field is a placeholder validate rejects."""
    out, index = safe_path(args.out), read_json(args.index)
    if out.exists():
        raise ValueError(f'{out} exists; scaffold never overwrites notes')
    todo = PLACEHOLDER + ' '
    sections = [{'title': todo + '节标题', 'short': todo + '目录短名', 'takeaway': todo + '一句话结论',
                 'start': c['start'], 'end': c['end'], 'source_ids': c['source_ids'],
                 'paragraphs': [todo + '按课堂原话整理的完整笔记'], 'examples': [], 'editor_notes': [], 'frames': [], 'terms': []}
                for c in index['chunks']]
    note = {'schema_version': 3, 'title': args.title or todo + '课程标题', 'short_title': todo + '短标题',
            'source_url': args.source_url or '', 'read_chunks': [], 'omitted': [], 'summary': [todo + '本课主线'],
            'sections': sections, 'supplements': [], 'self_test': [],
            'limitations': [todo + '实际读过哪些分块、看过哪些画面、哪些没核对']}
    write(out, dump(note) + '\n')
    print(dump({'output': str(out), 'sections': len(sections),
                'next': 'Read every chunk, regroup sections by real topics (merge/split; keep source_ids contiguous), '
                        'fill every placeholder, list read chunk IDs in read_chunks, then run validate.'}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('chunks'); c.add_argument('--input', required=True); c.add_argument('--out', required=True); c.set_defaults(fn=chunks)
    r = sub.add_parser('render'); r.add_argument('--notes', required=True); r.add_argument('--index', required=True); r.add_argument('--out', required=True); r.add_argument('--layout'); r.add_argument('--require-layout', action='store_true'); r.set_defaults(fn=render)
    v = sub.add_parser('validate', help='report every notes problem at once'); v.add_argument('--notes', required=True); v.add_argument('--index', required=True); v.add_argument('--layout'); v.set_defaults(fn=validate)
    s = sub.add_parser('scaffold', help='v3 skeleton from chunks/index.json'); s.add_argument('--index', required=True); s.add_argument('--out', required=True); s.add_argument('--title'); s.add_argument('--source-url'); s.set_defaults(fn=scaffold)
    args = p.parse_args()
    try:
        result = args.fn(args)
        if args.command == 'validate' and result['status'] == 'failed':
            p.exit(1)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        p.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
