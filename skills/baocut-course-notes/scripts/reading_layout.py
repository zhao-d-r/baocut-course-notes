"""Validated editorial layout over notes v2; never infers semantic placement."""
import hashlib
import html
import re
from pathlib import Path

def issue_badge(issue):
    """The big decorative number in the hero: only a short lecture number ("07", "第 8 讲", "L10").

    Writers often put a long label in `issue` ("Breakout Session · Turing Room · 2026-10-14"); shown at
    140px in an auto-width grid column it squeezed the title to one character per line.
    """
    m = re.fullmatch(r'\s*(?:第\s*|L|Lecture\s*)?(\d{1,3})\s*[讲课]?\s*', str(issue or ''), re.I)
    return m[1].zfill(2) if m else ''


FIELDS = {'p': 'paragraphs', 'e': 'examples', 'n': 'editor_notes', 'f': 'frames'}


def esc(text):
    if not isinstance(text, str):
        raise ValueError('Layout content must be plain text')
    return html.escape(text, quote=True)


def supplements(note):
    if note.get('supplements') and note.get('official_slide_supplements'):
        raise ValueError('Use supplements or legacy supplements, not both')
    return note.get('supplements') or note.get('official_slide_supplements', [])


def resolve(token, section):
    match = re.fullmatch(r'([penfx])(\d+)(?::(\d+))?', token)
    if not match:
        raise ValueError('Invalid reading flow token: ' + str(token))
    kind, first, second = match.groups()
    if second is not None:
        if kind != 'f' or int(first) < 1:
            raise ValueError('Only PDF figures support cross-section placement')
        return kind, int(first) - 1, int(second)
    return kind, -1 if kind == 'x' else section, int(first)


def validate(note, layout, note_bytes):
    if layout.get('version') != 1:
        raise ValueError('Unsupported reading-layout version')
    if layout.get('notes_sha256') != hashlib.sha256(note_bytes).hexdigest():
        raise ValueError('Stale reading layout: notes_sha256 does not match notes.json')
    sections = note['sections']
    if len(layout.get('sections', [])) != len(sections):
        raise ValueError('Layout must cover every section')
    summary_terms = layout.get('summary_terms', [])
    if not isinstance(summary_terms, list) or any(not isinstance(t, str) or not t.strip() for t in summary_terms):
        raise ValueError('Summary emphasis terms must be nonempty plain strings')
    if any(not any(t in p for p in note.get('summary', [])) for t in summary_terms):
        raise ValueError('Summary emphasis term not found in summary')
    expected = {(kind, i, j) for i, s in enumerate(sections) for kind, field in FIELDS.items() for j in range(len(s.get(field, [])))}
    expected.update(('x', -1, j) for j in range(len(supplements(note))))
    seen, placements = set(), []
    for i, entry in enumerate(layout['sections']):
        for key in ['short', 'takeaway']:
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError('Layout section requires ' + key)
        if not isinstance(entry.get('flow'), str):
            raise ValueError('Section flow must be a token string')
        block_text = []
        for token in entry['flow'].split():
            key = resolve(token, i)
            if key not in expected:
                raise ValueError('Unknown or out-of-range layout reference: ' + token)
            if key in seen:
                raise ValueError('Duplicate layout reference: ' + token)
            seen.add(key)
            kind, owner, index = key
            if kind == 'f':
                frame = sections[owner]['frames'][index]
                if owner != i and frame.get('source_type', 'video_frame') != 'pdf_page':
                    raise ValueError('Video frame must remain in its timed section')
                placements.append({'source_section': owner + 1, 'frame': index, 'display_section': i + 1, 'path': frame['path']})
            elif kind == 'x':
                block_text.append(supplements(note)[index]['text'])
            else:
                block_text.append(sections[owner][FIELDS[kind]][index])
        terms = entry.get('terms', [])
        if not isinstance(terms, list) or any(not isinstance(t, str) or not t.strip() for t in terms):
            raise ValueError('Emphasis terms must be nonempty plain strings')
        missing_terms = [t for t in terms if not any(t in text for text in block_text)]
        if missing_terms:
            raise ValueError(f'Section {i+1} emphasis terms not found in displayed prose: {missing_terms}')
    if seen != expected:
        raise ValueError('Reading layout omits content: ' + str(sorted(expected - seen)))
    starts = []
    for group in layout.get('groups', []):
        start = group.get('start')
        if isinstance(start, bool) or not isinstance(start, int) or not 1 <= start <= len(sections) or start in starts:
            raise ValueError('Invalid or repeated navigation group start')
        starts.append(start)
        esc(group['label'])
    for token, text in layout.get('bridges', {}).items():
        if not re.fullmatch(r'x\d+', token) or int(token[1:]) >= len(supplements(note)):
            raise ValueError('Bridge must reference an existing supplement')
        esc(text)
    return {'status': 'passed', 'content_units': len(expected), 'figures': len(placements), 'supplements': len(supplements(note)), 'placements': placements,
            'boundary': 'Structural coverage and version binding only; requires semantic and browser review.'}


def emphasize(text, terms):
    spans = []
    for term in terms:
        start = text.find(term)
        if start >= 0 and not any(start < end and start + len(term) > begin for begin, end in spans):
            spans.append((start, start + len(term)))
        if len(spans) == 2:
            break
    parts, cursor = [], 0
    for start, end in sorted(spans):
        parts += [esc(text[cursor:start]), '<strong>' + esc(text[start:end]) + '</strong>']
        cursor = end
    return ''.join(parts) + esc(text[cursor:])


def render(note, layout, note_bytes, base, assets):
    report = validate(note, layout, note_bytes)
    # The base renderer has already checked evidence ownership, frame times, paths,
    # data types, physical pages, source URLs and all optional content fields.
    figures = {}
    for i, section in enumerate(note['sections']):
        block = re.search(rf'<section id="s{i+1}">.*?</section>', base, re.S).group()
        rendered = re.findall(r'<figure>.*?</figure>', block, re.S)
        if len(rendered) != len(section.get('frames', [])):
            raise ValueError('Base renderer figure contract changed')
        for j, (frame, figure) in enumerate(zip(section.get('frames', []), rendered)):
            provenance = re.search(r'<figcaption>(.*?)</figcaption>', figure, re.S).group(1)
            label = f'资料图 · 第 {frame["page"]} 页' if frame.get('source_type') == 'pdf_page' else '视频原帧'
            caption = f'<figcaption><span class="figure-label">{label}</span>{esc(frame["caption"])}<span class="figure-hint">点击图片查看细节 ↗</span><details class="figure-provenance"><summary>来源与时间</summary><p>{provenance}</p></details></figcaption>'
            figures[(i, j)] = re.sub(r'<figcaption>.*?</figcaption>', lambda _: caption, figure, flags=re.S).replace('<figure>', f'<figure data-frame="{i+1}:{j}">', 1)
    body = ''
    if note.get('summary'):
        body += '<section id="summary"><div class="section-heading">阅读导引</div><h2>' + esc(layout.get('summary_title', '先把握本课主线')) + '</h2><div class="summary-list">'
        body += ''.join('<p class="summary-item">' + emphasize(p, layout.get('summary_terms', [])) + '</p>' for p in note['summary'])
        body += '</div></section>'
    for i, (section, entry) in enumerate(zip(note['sections'], layout['sections'])):
        old = re.search(rf'<section id="s{i+1}">.*?</section>', base, re.S).group()
        time = re.search(r'<small>(.*?)</small>', old, re.S).group(1)
        body += f'<section id="s{i+1}"><div class="section-heading"><span>第 {i+1:02d} 节</span><small>{time} · 课堂时间</small></div><h2>{esc(section["title"])}</h2><div class="section-takeaway"><span class="takeaway-label">关键判断 · 整理者提炼</span><p>{esc(entry["takeaway"])}</p></div>'
        tokens = entry['flow'].split()
        extension_open = False
        for token in tokens:
            kind, owner, index = resolve(token, i)
            if extension_open and kind != 'f':
                body += '</div>'
                extension_open = False
            if kind == 'f':
                body += figures[(owner, index)]
            elif kind == 'x':
                item = supplements(note)[index]
                body += f'<div class="inline-reading" id="supplement-{index}"><div class="source-tag">{esc(item.get("source_label", "官方讲义"))}</div><h3>{esc(item["title"])}</h3>'
                if token in layout.get('bridges', {}):
                    body += '<p class="bridge">整理者衔接：' + esc(layout['bridges'][token]) + '</p>'
                body += f'<p data-content="x{index}">' + emphasize(item['text'], entry['terms']) + '</p>'
                origin = []
                if item.get('pages'):
                    origin.append('PDF物理页 ' + '、'.join(str(p) for p in item['pages']))
                if item.get('source_url'):
                    origin.append('<a href="' + esc(item['source_url']) + '">原始资料 ↗</a>')
                body += '<p class="source-tag">' + ' · '.join(origin) + '</p>'
                extension_open = True
            else:
                text = emphasize(section[FIELDS[kind]][index], entry['terms'])
                if kind == 'n':
                    body += f'<p class="inline-note" data-content="s{i+1}:n{index}"><span class="source-tag">整理者说明</span><br>{text}</p>'
                elif kind == 'e':
                    body += f'<p class="example" data-content="s{i+1}:e{index}"><span class="example-label">案例回扣</span>{text}</p>'
                else:
                    body += f'<p data-content="s{i+1}:p{index}">{text}</p>'
        if extension_open:
            body += '</div>'
        body += '</section>'
    tests = note.get('self_test', [])
    if tests:
        body += '<section id="self-test"><h2>自测：先回答，再核对</h2><p class="quiz-intro">先用自己的话回答，再展开参考答案；答不清楚时，回到对应知识点。</p>'
        for i, item in enumerate(tests, 1):
            terms = layout['sections'][item['section'] - 1]['terms'] if item.get('section') else []
            link = f'<a href="#s{item["section"]}">回查第 {item["section"]} 节 →</a>' if item.get('section') else ''
            body += f'<article class="quiz-card"><div class="quiz-question"><div class="quiz-kicker">问题 {i:02d}</div><h3 id="q{i}">{esc(item["question"])}</h3></div><details class="quiz-answer"><summary aria-describedby="q{i}"><span class="answer-action-open">查看参考答案</span><span class="answer-action-close">收起参考答案</span></summary><div class="answer-body"><div class="answer-label">参考答案 · 核对思路</div><p>{emphasize(item["answer"], terms)}</p>{link}</div></details></article>'
        body += '</section>'
    count = len(note['sections'])
    toc = f'<details class="course-toc" open><summary>阅读目录 · {count} 节</summary><nav aria-label="课程目录">'
    if note.get('summary'):
        toc += '<a href="#summary">本课主线</a>'
    groups = {x['start']: x['label'] for x in layout.get('groups', [])}
    for i, entry in enumerate(layout['sections'], 1):
        if i in groups:
            toc += '<div class="toc-group">' + esc(groups[i]) + '</div>'
        toc += f'<a href="#s{i}"><span>{i:02d}</span>{esc(entry["short"])}</a>'
    if tests:
        toc += f'<div class="toc-group">复习</div><a href="#self-test">{len(tests)} 道自测</a>'
    toc += '</nav></details>'
    values = {'TITLE': esc(note['title']), 'COURSE': esc(layout.get('course_title', '课程学习笔记')),
              'ISSUE': esc(layout.get('issue', '')), 'BADGE': issue_badge(layout.get('issue')), 'HEADING': esc(layout.get('title', note['title'])),
              'SUBTITLE': esc(layout.get('subtitle', '')), 'META': f'{count} 节 · {len(figures)} 幅配图 · {len(tests)} 道自测',
              'SOURCE': '<a href="' + esc(note['source_url']) + '">回看课堂 ↗</a>' if note.get('source_url') else '',
              'LIMITS': ''.join('<p>' + esc(t) + '</p>' for t in note['limitations']), 'TOC': toc, 'BODY': body,
              'STYLE': (assets / 'editorial.css').read_text(encoding='utf-8'), 'SCRIPT': (assets / 'editorial.js').read_text(encoding='utf-8')}
    template = (assets / 'editorial.html').read_text(encoding='utf-8')
    page = re.sub(r'\{\{([A-Z]+)\}\}', lambda m: values[m[1]], template)
    return page, report
