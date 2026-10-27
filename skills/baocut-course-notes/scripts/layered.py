"""Layered reading page for notes v3: course map -> one card per point -> full notes.

The layout lives inside notes.json, so there is no separate layout file to bind by hash.
Validation is structural only; fidelity of takeaways and explainer diagrams is checked by
fidelity_eval.py against an independent review.
"""
import base64
from pathlib import Path

from course_notes import Problems, esc, figure_source, safe_path, seconds, stamp, text_of
from reading_layout import FIELDS, emphasize, resolve, supplements

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
REF_LABELS = {'p': '课堂段落', 'e': '课堂案例', 'n': '整理者说明', 'x': '外部资料', 'f': '原帧'}


RASTER = {b'\x89PNG\r\n\x1a\n': 'image/png', b'\xff\xd8\xff': 'image/jpeg', b'RIFF': 'image/webp'}
MAX_RASTER = 3_000_000


def svg_uri(item, run_dir, where):
    """Data URI for an explainer: a plain SVG, or a generated PNG/JPEG/WebP illustration whose
    visible text is declared in `labels` so reviewers can check every word drawn into the pixels."""
    if not isinstance(item, dict) or not isinstance(item.get('path'), str) or not isinstance(item.get('alt'), str) or not item['alt'].strip():
        raise ValueError(where + ' visual needs path and alt text')
    path = safe_path(Path(run_dir) / item['path'])
    suffix = path.suffix.lower()
    if not path.is_relative_to(Path(run_dir).resolve()) or suffix not in ('.svg', '.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError(where + ' visual must be an .svg or .png/.jpg/.webp inside the run directory')
    data = path.read_bytes()
    if suffix != '.svg':
        mime = next((m for magic, m in RASTER.items() if data.startswith(magic) and (magic != b'RIFF' or data[8:12] == b'WEBP')), None)
        if not mime:
            raise ValueError(f'{where} visual {item["path"]} is not a PNG/JPEG/WebP file')
        labels = item.get('labels')
        if not isinstance(labels, list) or not labels or any(not isinstance(t, str) or not t.strip() for t in labels):
            raise ValueError(f'{where} illustration needs labels: every text string visible in the image, for review')
        if len(data) > MAX_RASTER:
            raise ValueError(f'{where} illustration is {len(data) // 1000} KB; compress to under {MAX_RASTER // 1_000_000} MB (e.g. sips -Z 1536 / WebP)')
        return f'data:{mime};base64,' + base64.b64encode(data).decode('ascii')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError(f'{where} visual {item["path"]} is not UTF-8 (byte {exc.start}); write SVG files as UTF-8, e.g. with svgcard.py') from None
    if '<svg' not in text[:400] or '<!ENTITY' in text:
        raise ValueError(where + ' visual is not a plain SVG file')
    # Embedded through <img>, so any script or external reference inside the SVG never runs.
    return 'data:image/svg+xml;base64,' + base64.b64encode(data).decode('ascii')


def section_tokens(section, i, entry_flow):
    if entry_flow is None:
        return [f'{k}{j}' for k, field in FIELDS.items() for j in range(len(section.get(field, [])))]
    if not isinstance(entry_flow, str):
        raise ValueError(f'Section {i+1} flow must be a token string')
    return entry_flow.split()


def validate(note, run_dir, problems=None):
    """Structural checks for the layered page. With a Problems list, collects every failure
    with its field path; without one, raises the first (render behaviour)."""
    local = problems is None
    problems = Problems() if local else problems
    if note.get('schema_version') != 3:
        raise ValueError('Layered rendering requires notes schema_version 3')
    sections = note.get('sections') or []
    supp = supplements(note)
    expected = {(kind, i, j) for i, s in enumerate(sections) for kind, field in FIELDS.items() for j in range(len(s.get(field, [])))}
    seen, flows, visuals = set(), [], 0

    def place(token, i, shown):
        key = resolve(token, i)
        kind, owner, index = key
        if kind == 'x':
            if index >= len(supp):
                raise ValueError('Unknown supplement reference: ' + token)
        elif key not in expected:
            raise ValueError('Unknown or out-of-range content reference: ' + token)
        if key in seen:
            raise ValueError('Duplicate content reference: ' + token)
        seen.add(key)
        if kind == 'f' and owner != i and sections[owner]['frames'][index].get('source_type', 'video_frame') != 'pdf_page':
            raise ValueError('Video frame must remain in its timed section')
        if kind == 'x':
            shown.append(supp[index]['text'])
        elif kind != 'f':
            shown.append(text_of(sections[owner][FIELDS[kind]][index]))

    def visual(s, i, tokens):
        svg_uri(s['visual'], run_dir, f'Section {i+1}')
        refs = s['visual'].get('refs')
        if not isinstance(refs, list) or not refs or any(r not in tokens for r in refs):
            raise ValueError(f'Section {i+1} visual refs must list the full-note tokens it is drawn from')

    for i, s in enumerate(sections):
        where = f'sections[{i}]'
        for key in ('short', 'takeaway'):
            if not isinstance(s.get(key), str) or not s[key].strip():
                problems.append((f'{where}.{key}', ValueError(f'Section {i+1} requires {key}')))
        tokens, shown = problems.attempt(f'{where}.flow', section_tokens, s, i, s.get('flow')) or [], []
        for token in tokens:
            problems.attempt(f'{where}.flow:{token}', place, token, i, shown)
        terms = s.get('terms', [])
        if not isinstance(terms, list) or any(not isinstance(t, str) or not t.strip() for t in terms):
            problems.append((f'{where}.terms', ValueError('Emphasis terms must be nonempty plain strings')))
        else:
            missing = [t for t in terms if not any(t in text for text in shown)]
            if missing:
                problems.append((f'{where}.terms', ValueError(f'Section {i+1} emphasis terms not found in its full notes: {missing}')))
        if s.get('visual') is not None:
            before = len(problems)
            problems.attempt(f'{where}.visual', visual, s, i, tokens)
            visuals += len(problems) == before
        flows.append(tokens)
    missing = {k for k in expected if k not in seen}
    if missing:
        problems.append(('sections[].flow', ValueError('Layered page omits content: ' + str(sorted(missing)))))
    if note.get('map') is not None:
        before = len(problems)
        problems.attempt('map', svg_uri, note['map'], run_dir, 'Course map')
        visuals += len(problems) == before
    starts = []
    for j, group in enumerate(note.get('groups', [])):
        start = group.get('start')
        if isinstance(start, bool) or not isinstance(start, int) or not 1 <= start <= len(sections) or start in starts:
            problems.append((f'groups[{j}]', ValueError('Invalid or repeated navigation group start')))
            continue
        problems.attempt(f'groups[{j}].label', esc, group.get('label'))
        starts.append(start)
    for token, text in note.get('bridges', {}).items():
        if not isinstance(token, str) or not token[1:].isdigit() or token[0] != 'x' or int(token[1:]) >= len(supp):
            problems.append((f'bridges.{token}', ValueError('Bridge must reference an existing supplement')))
        else:
            problems.attempt(f'bridges.{token}', esc, text)
    if local and problems:
        raise problems[0][1]
    unplaced = [j for j in range(len(supp)) if ('x', -1, j) not in seen]
    return flows, unplaced, visuals


def caveat_html(item):
    if isinstance(item, dict) and item.get('caveat'):
        return '<span class="caveat"><b>核对与边界</b>' + esc(item['caveat']) + '</span>'
    return ''


def supplement_html(item, index, terms, bridge=None):
    origin = []
    if item.get('pages'):
        origin.append('PDF物理页 ' + '、'.join(str(p) for p in item['pages']))
    if item.get('source_url'):
        origin.append('<a href="' + esc(item['source_url']) + '">原始资料 ↗</a>')
    return (f'<div class="inline-reading" id="supplement-{index}"><span class="chip chip-external">外部资料</span>'
            f'<div class="source-tag">{esc(item.get("source_label", "官方讲义"))}</div><h3>{esc(item["title"])}</h3>'
            + (f'<p class="bridge">整理者衔接：{esc(bridge)}</p>' if bridge else '') +
            f'<p data-content="x{index}">{emphasize(item["text"], terms)}</p><p class="source-tag">{" · ".join(origin)}</p>')


def render(note, run_dir):
    flows, unplaced, visual_count = validate(note, run_dir)
    sections, supp = note['sections'], supplements(note)
    figures, frame_count = {}, 0
    for i, s in enumerate(sections):
        start, end = seconds(s['start']), seconds(s['end'])
        for j, frame in enumerate(s.get('frames', [])):
            origin, uri = figure_source(frame, run_dir, start, end)
            caption = esc(frame['caption'])
            label = f'资料图 · 第 {frame["page"]} 页' if frame.get('source_type') == 'pdf_page' else '视频原帧'
            figures[(i, j)] = (f'<figure data-frame="{i+1}:{j}"><button class="zoom" aria-label="放大：{caption}"><img src="{uri}" alt="{caption}" loading="lazy"></button>'
                               f'<figcaption><span class="figure-label">{label}</span>{caption}<span class="figure-hint">点击图片查看细节 ↗</span>'
                               f'<details class="figure-provenance"><summary>来源与时间</summary><p>{origin} · {caption}</p></details></figcaption></figure>')
            frame_count += 1
    body = '<section id="map" class="map"><div class="section-heading">一张图看懂本课</div>'
    if note.get('map'):
        m = note['map']
        body += f'<figure class="explainer"><button class="zoom" aria-label="放大课程地图"><img src="{svg_uri(m, run_dir, "Course map")}" alt="{esc(m["alt"])}"></button><figcaption><span class="chip chip-editor">整理者图解</span>{esc(m.get("caption", "按本课各节关键判断绘制"))}</figcaption></figure>'
    if note.get('summary'):
        body += '<h2>' + esc(note.get('summary_title', '先把握本课主线')) + '</h2><div class="summary-list">'
        body += ''.join('<p class="summary-item">' + emphasize(text_of(p), note.get('summary_terms', [])) + '</p>' for p in note['summary'])
        body += '</div>'
    body += ('<p class="legend"><span class="chip chip-lecture">课堂</span>讲师讲述（默认，不另加标签） '
             '<span class="chip chip-editor">整理者</span>提炼、图解与说明 <span class="chip chip-external">外部资料</span>课外核对来源</p></section>')
    for i, (s, tokens) in enumerate(zip(sections, flows)):
        terms = s.get('terms', [])
        body += (f'<section id="s{i+1}" class="card"><div class="section-heading"><span>第 {i+1:02d} 节</span><small>{stamp(s["start"])}—{stamp(s["end"])} · 课堂时间</small></div>'
                 f'<h2>{esc(s["title"])}</h2><p class="takeaway"><span class="chip chip-editor">一句话</span>{esc(s["takeaway"])}</p>')
        if s.get('visual'):
            v = s['visual']
            refs = ' '.join(f'<a class="ref" href="#s{i+1}-{r}"><span class="item-no">{tokens.index(r) + 1}</span>{REF_LABELS[r[0]]}</a>' for r in v['refs'])
            body += (f'<figure class="explainer"><button class="zoom" aria-label="放大图解：{esc(v["alt"])}"><img src="{svg_uri(v, run_dir, "Section")}" alt="{esc(v["alt"])}"></button>'
                     f'<figcaption><span class="chip chip-editor">整理者图解</span>依据完整笔记 {refs}</figcaption></figure>')
        counts = {}
        for t in tokens:
            counts[t[0]] = counts.get(t[0], 0) + 1
        summary = ' · '.join(f'{n} 条{REF_LABELS[k]}' for k, n in counts.items())
        body += f'<details class="deep"><summary><span class="deep-open">展开完整笔记</span><span class="deep-close">收起完整笔记</span><small>{summary}</small></summary><div class="deep-body">'
        extension_open = False
        for n, token in enumerate(tokens, 1):
            kind, owner, index = resolve(token, i)
            if extension_open and kind != 'f':
                body += '</div>'
                extension_open = False
            anchor = f'<span class="item-no" id="s{i+1}-{token}">{n}</span>'
            if kind == 'f':
                body += figures[(owner, index)].replace('<figure ', f'<figure id="s{i+1}-{token}" ', 1).replace('<figcaption>', f'<figcaption><span class="item-no">{n}</span>', 1)
            elif kind == 'x':
                body += supplement_html(supp[index], index, terms, note.get('bridges', {}).get(token)).replace('<span class="chip', anchor + '<span class="chip', 1)
                extension_open = True
            else:
                item = s[FIELDS[kind]][index]
                text = emphasize(text_of(item), terms)
                if kind == 'n':
                    body += f'<p class="inline-note" data-content="s{i+1}:n{index}">{anchor}<span class="chip chip-editor">整理者说明</span><br>{text}{caveat_html(item)}</p>'
                elif kind == 'e':
                    body += f'<p class="example" data-content="s{i+1}:e{index}">{anchor}<span class="chip chip-lecture">课堂案例</span>{text}{caveat_html(item)}</p>'
                else:
                    body += f'<p data-content="s{i+1}:p{index}">{anchor}{text}{caveat_html(item)}</p>'
        if extension_open:
            body += '</div>'
        body += '</div></details></section>'
    if unplaced:
        body += '<section id="extensions"><h2>延伸资料</h2><p class="quiz-intro">以下补充未放入具体知识点，单独列出。</p>'
        body += ''.join(supplement_html(supp[j], j, [], note.get('bridges', {}).get(f'x{j}')) + '</div>' for j in unplaced) + '</section>'
    tests = note.get('self_test', [])
    if tests:
        body += '<section id="self-test"><h2>自测：先回答，再核对</h2><p class="quiz-intro">先用自己的话回答，再展开参考答案；答不清楚时，回到对应知识点。</p>'
        for n, item in enumerate(tests, 1):
            link = f'<a href="#s{item["section"]}">回查第 {item["section"]} 节 →</a>' if item.get('section') else ''
            body += (f'<article class="quiz-card"><div class="quiz-question"><div class="quiz-kicker">问题 {n:02d}</div><h3 id="q{n}">{esc(item["question"])}</h3></div>'
                     f'<details class="quiz-answer"><summary aria-describedby="q{n}"><span class="answer-action-open">查看参考答案</span><span class="answer-action-close">收起参考答案</span></summary>'
                     f'<div class="answer-body"><div class="answer-label">参考答案 · 核对思路</div><p>{esc(item["answer"])}</p>{link}</div></details></article>')
        body += '</section>'
    toc = f'<details class="course-toc" open><summary>阅读目录 · {len(sections)} 节</summary><nav aria-label="课程目录"><a href="#map">一张图看懂本课</a>'
    groups = {g['start']: g['label'] for g in note.get('groups', [])}
    for i, s in enumerate(sections, 1):
        if i in groups:
            toc += '<div class="toc-group">' + esc(groups[i]) + '</div>'
        mark = ' ◆' if s.get('visual') else ''
        toc += f'<a href="#s{i}"><span>{i:02d}</span>{esc(s["short"])}{mark}</a>'
    if tests:
        toc += f'<div class="toc-group">复习</div><a href="#self-test">{len(tests)} 道自测</a>'
    toc += '</nav></details>'
    url = note.get('source_url')
    values = {'TITLE': esc(note['title']), 'COURSE': esc(note.get('course_title', '课程学习笔记')),
              'ISSUE': esc(note.get('issue', '')), 'HEADING': esc(note.get('heading', note['title'])),
              'SUBTITLE': esc(note.get('subtitle', '')),
              'META': f'{len(sections)} 节 · {visual_count} 张图解 · {frame_count} 幅原帧 · {len(tests)} 道自测',
              'SOURCE': '<a href="' + esc(url) + '">回看课堂 ↗</a>' if url else '',
              'LIMITS': ''.join('<p>' + esc(text_of(t)) + '</p>' for t in note['limitations']), 'TOC': toc, 'BODY': body,
              'STYLE': (ASSETS / 'editorial.css').read_text(encoding='utf-8') + (ASSETS / 'layered.css').read_text(encoding='utf-8'),
              'SCRIPT': (ASSETS / 'editorial.js').read_text(encoding='utf-8') + (ASSETS / 'layered.js').read_text(encoding='utf-8')}
    import re
    template = (ASSETS / 'layered.html').read_text(encoding='utf-8')
    page = re.sub(r'\{\{([A-Z]+)\}\}', lambda m: values[m[1]], template)
    return page, {'visuals': visual_count, 'frames': frame_count, 'unplaced_supplements': len(unplaced)}
