#!/usr/bin/env python3
"""Fidelity eval: precision (what the notes say is supported) and recall (what the lecture
taught can be answered from the notes). Judgments come from reviewers running a different
model; this script builds their packets, merges their answers and checks binding, coverage
and arithmetic, never the semantics.

  prepare --notes N --index I --out DIR      reviewer packets + RUN.md with external-CLI commands
  prepare ... --light                        production light check: top-layer precision packet only
  blind   --dir DIR                          strip expected answers for the answerer
  merge   --notes N --dir DIR --out EVAL --writer-model M --reviewer-model R --author-model A --answerer-model B
  stale   --notes N --eval EVAL              items whose content changed since review (incremental re-review)
  score   --notes N --eval EVAL              (default when no subcommand is given)
          [--ledger L --skill-version V --source-type T]   also record the result in the course ledger
  mode    --ledger L --writer-model M --skill-version V --source-type T   light or full eval for the next lesson
  review  --notes N --dir DIR --out EVAL --writer-model M [--update EVAL]
          runs every packet in DIR with a reviewer CLI of another family, records tokens, then merges
"""
import argparse
import datetime as dt
import hashlib
import html as htmllib
import json
import random
import re
import subprocess
import sys
import threading
from types import SimpleNamespace
from pathlib import Path

from course_notes import dump, read_json, safe_path, stamp, text_of, write
from reading_layout import FIELDS, supplements

PRECISION = {'supported': 1.0, 'partial': 0.5, 'unsupported': 0.0, 'distorted': 0.0}
RECALL = {'correct': 1.0, 'partial': 0.5, 'missing': 0.0, 'wrong': 0.0}
ROLES = ('independent_agent', 'human', 'same_agent')
DEFAULTS = {'min_precision': 0.95, 'min_recall': 0.85, 'min_questions': 20}
AUDIT_EVERY = 5  # in production, every 5th lesson of an approved combination gets the full eval
REVIEWERS = {'cursor': 'grok-4.7-high', 'codex': 'gpt-6.1-sol'}  # default model per reviewer CLI
# role -> (packet folder, prompt file, output the role must write)
STEPS = {'precision': ('precision', 'PROMPT.md', 'precision/results.json'), 'author': ('author', 'PROMPT.md', 'author/questions.json'),
         'answer': ('answer', 'PROMPT.md', 'answer/answers.json'), 'grade': ('author', 'GRADE.md', 'author/grades.json')}


def is_top(ref):
    return ref == 'map' or bool(re.fullmatch(r's\d+:(takeaway|visual)', ref))


def refs_in(notes):
    """Every reference a precision item may point at."""
    refs = set()
    if notes.get('map'):
        refs.add('map')
    for i, s in enumerate(notes['sections'], 1):
        refs.update({f's{i}:takeaway', f's{i}:title'})
        if s.get('visual'):
            refs.add(f's{i}:visual')
        for kind, field in FIELDS.items():
            refs.update(f's{i}:{kind}{j}' for j in range(len(s.get(field, []))))
    refs.update(f'x{j}' for j in range(len(supplements(notes))))
    refs.update(f'q{j}' for j in range(1, len(notes.get('self_test', [])) + 1))
    refs.update(f'summary{j}' for j in range(len(notes.get('summary', []))))
    return refs


def svg_text(item, run_dir):
    if item and item.get('labels'):
        return ' / '.join(item['labels'])  # generated illustration: reviewers check the image against these
    if not item or not run_dir:
        return ''
    try:
        raw = (Path(run_dir) / item['path']).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError, KeyError):
        return ''
    return ' / '.join(htmllib.unescape(t) for t in re.findall(r'<text[^>]*>(.*?)</text>', raw, re.S) if t.strip())


def unit_text(notes, ref, run_dir=None):
    """The exact content a reviewer judges for one ref; its hash binds the judgment."""
    if ref == 'map':
        m = notes['map']
        return f"{m.get('alt', '')} | {m.get('caption', '')} | {svg_text(m, run_dir)}"
    if m := re.fullmatch(r'summary(\d+)', ref):
        return text_of(notes['summary'][int(m[1])])
    if m := re.fullmatch(r'x(\d+)', ref):
        x = supplements(notes)[int(m[1])]
        return f"{x.get('title', '')} | {x.get('text', '')}"
    if m := re.fullmatch(r'q(\d+)', ref):
        q = notes['self_test'][int(m[1]) - 1]
        return f"{q['question']} | {q['answer']}"
    i, part = re.fullmatch(r's(\d+):(\w+)', ref).groups()
    s = notes['sections'][int(i) - 1]
    if part in ('takeaway', 'title'):
        return s[part]
    if part == 'visual':
        return f"{s['visual'].get('alt', '')} | {svg_text(s['visual'], run_dir)}"
    item = s[FIELDS[part[0]]][int(part[1:])]
    if part[0] == 'f':
        return f"{item.get('caption', '')} | {item.get('path', '')} | {item.get('time', item.get('page', ''))}"
    return text_of(item) + (' | ' + item['caveat'] if isinstance(item, dict) and item.get('caveat') else '')


def item_hashes(notes, run_dir=None):
    return {r: hashlib.sha256(unit_text(notes, r, run_dir).encode('utf-8')).hexdigest()[:16] for r in sorted(refs_in(notes))}


def scope_hash(hashes, found_in):
    """Recall answers depend on the sections they were found in; missing answers on the whole notes."""
    secs = set(re.findall(r's(\d+)', found_in or ''))
    keys = [k for k in hashes if not secs or (k.startswith('s') and k.split(':')[0][1:] in secs)]
    return hashlib.sha256(''.join(f'{k}={hashes[k]}' for k in sorted(keys)).encode()).hexdigest()[:16]


def stale_items(report, notes, run_dir=None):
    hashes = item_hashes(notes, run_dir)
    p = [i['ref'] for i in (report.get('precision') or {}).get('items', []) if hashes.get(i['ref']) != i.get('hash')]
    r = [i['id'] for i in (report.get('recall') or {}).get('items', []) if scope_hash(hashes, i.get('found_in')) != i.get('hash')]
    return p, r


def per_item_bound(report):
    items = (report.get('precision') or {}).get('items', []) + (report.get('recall') or {}).get('items', [])
    return bool(items) and all(isinstance(i.get('hash'), str) for i in items)


def score(report, notes, limits=None):
    limits = {**DEFAULTS, **(limits or {})}
    if report.get('schema_version') != 1:
        raise ValueError('Expected fidelity eval schema_version 1')
    problems = []
    known = refs_in(notes)
    precision = report.get('precision') or {}
    p_items = precision.get('items') or []
    for item in p_items:
        if item.get('ref') not in known:
            raise ValueError('Precision item points at unknown ref: ' + str(item.get('ref')))
        if item.get('verdict') not in PRECISION:
            raise ValueError('Invalid precision verdict for ' + item['ref'])
        if not isinstance(item.get('evidence'), str) or not item['evidence'].strip():
            raise ValueError('Precision item needs the source evidence it was checked against: ' + item['ref'])
    checked = {i['ref'] for i in p_items}
    top_layer = {r for r in known if r == 'map' or re.fullmatch(r's\d+:(takeaway|visual)', r)}
    unchecked = sorted(top_layer - checked)
    if unchecked:
        problems.append('Every takeaway and explainer must be checked; missing: ' + ', '.join(unchecked))
    bad_top = sorted(i['ref'] for i in p_items if i['ref'] in top_layer and i['verdict'] in ('unsupported', 'distorted'))
    if bad_top:
        problems.append('Unsupported or distorted takeaway/explainer: ' + ', '.join(bad_top))
    if report.get('mode') == 'light':
        return light_score(precision, p_items, top_layer, problems)
    recall = report.get('recall') or {}
    r_items = recall.get('items') or []
    for item in r_items:
        expected = item.get('expected')
        expected = ' '.join(expected) if isinstance(expected, list) and all(isinstance(x, str) for x in expected) else expected
        for value in (item.get('id'), item.get('question'), expected, item.get('evidence')):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Recall item needs id, question, expected answer and transcript/frame evidence')
        if item.get('verdict') not in RECALL or item.get('from') not in ('transcript', 'visual'):
            raise ValueError('Invalid recall verdict/from for ' + item['id'])
    if len(r_items) < limits['min_questions']:
        problems.append(f'Only {len(r_items)} recall questions; need at least {limits["min_questions"]}')
    if any(s.get('frames') for s in notes['sections']) and not any(i['from'] == 'visual' for i in r_items):
        problems.append('Notes use frames but no recall question was drawn from the visuals')
    p_score = round(sum(PRECISION[i['verdict']] for i in p_items) / len(p_items), 4) if p_items else None
    r_score = round(sum(RECALL[i['verdict']] for i in r_items) / len(r_items), 4) if r_items else None
    if p_score is None or p_score < limits['min_precision']:
        problems.append(f'Precision {p_score} below {limits["min_precision"]}')
    if r_score is None or r_score < limits['min_recall']:
        problems.append(f'Recall {r_score} below {limits["min_recall"]}')
    roles = [precision.get('reviewer'), recall.get('question_author'), recall.get('answerer')]
    if any(r not in ROLES for r in roles):
        raise ValueError('reviewer, question_author and answerer must each be one of ' + ', '.join(ROLES))
    if problems:
        status = 'failed'
    elif 'same_agent' in roles:
        status = 'self_checked'
    else:
        status = 'passed'
    misses = [i['id'] for i in r_items if i['verdict'] in ('missing', 'wrong')]
    return {'status': status, 'precision': p_score, 'recall': r_score,
            'precision_items': len(p_items), 'recall_items': len(r_items),
            'recall_misses': misses, 'problems': problems, 'roles': roles,
            'claim': 'Scores restate reviewer judgments; they do not prove the reviewers read everything.'}


def light_score(precision, p_items, top_layer, problems):
    """Production check: only the top layer, judged by another model family; recall is not measured."""
    if precision.get('reviewer') not in ROLES:
        raise ValueError('reviewer must be one of ' + ', '.join(ROLES))
    if problems:
        status = 'failed'
    elif precision['reviewer'] == 'same_agent':
        status = 'self_checked'
    else:
        status = 'light_checked'
    p_score = round(sum(PRECISION[i['verdict']] for i in p_items) / len(p_items), 4) if p_items else None
    return {'status': status, 'mode': 'light', 'precision': p_score, 'recall': None,
            'precision_items': len(p_items), 'recall_items': 0,
            'partial_top': sorted(i['ref'] for i in p_items if i['ref'] in top_layer and i['verdict'] == 'partial'),
            'problems': problems, 'roles': [precision['reviewer']],
            'claim': 'Light check: top-layer precision only. Recall and full-note precision were not measured; '
                     'report the latest full eval of this writer model + skill version + source type alongside.'}


FAMILIES = {'opus': 'claude', 'sonnet': 'claude', 'haiku': 'claude', 'fable': 'claude', 'claude': 'claude',
            'codex': 'gpt', 'sol': 'gpt', 'luna': 'gpt', 'gpt': 'gpt', 'grok': 'grok', 'gemini': 'gemini', 'argon': 'gemini'}


def family(model):
    m = (model or '').lower()
    return next((fam for key, fam in FAMILIES.items() if key in m), m or None)


def role(model, writer):
    if not model:
        raise ValueError('Record which model did each review (--reviewer-model, --author-model, --answerer-model)')
    if model.strip().lower() == 'human':
        return 'human'
    return 'same_agent' if family(model) == family(writer) else 'independent_agent'


def transcript_rows(index_path):
    index = read_json(index_path)
    rows = {}
    for c in index['chunks']:
        for r in read_json(Path(index_path).parent / c['file']):
            rows[r['id']] = r
    return rows


def flatten(notes, run):
    out = []
    if notes.get('map'):
        out.append('[map] ' + unit_text(notes, 'map', run))
    for j, _ in enumerate(notes.get('summary', [])):
        out.append(f'[summary{j}] ' + unit_text(notes, f'summary{j}'))
    for i, s in enumerate(notes['sections'], 1):
        out.append(f"\n## s{i} {s['title']} ({stamp(s['start'])}-{stamp(s['end'])})")
        refs = [f's{i}:takeaway'] + ([f's{i}:visual'] if s.get('visual') else [])
        refs += [f's{i}:{k}{j}' for k in 'penf' for j in range(len(s.get(FIELDS[k], [])))]
        out.extend(f'[{r}] ' + unit_text(notes, r, run) for r in refs)
    out.extend(f'[x{j}] ' + unit_text(notes, f'x{j}') for j in range(len(supplements(notes))))
    return '\n'.join(out) + '\n'


def prepare(args):
    notes_path, out = safe_path(args.notes), safe_path(args.out)
    notes, run = read_json(notes_path), notes_path.parent
    if out.exists() and any(out.iterdir()):
        raise ValueError(f'{out} is not empty')
    rows = transcript_rows(safe_path(args.index))
    hashes = item_hashes(notes, run)
    rng = random.Random(args.seed)
    refs = ['map'] if notes.get('map') else []
    for i, s in enumerate(notes['sections'], 1):
        refs.append(f's{i}:takeaway')
        if s.get('visual'):
            refs.append(f's{i}:visual')
        body = [f's{i}:{k}{j}' for k in 'pen' for j in range(len(s.get(FIELDS[k], [])))]
        refs += rng.sample(body, min(args.per_section, len(body)))
        frames = [f's{i}:f{j}' for j in range(len(s.get('frames', [])))]
        refs += rng.sample(frames, min(1, len(frames)))
    refs += [f'q{j}' for j in range(1, len(notes.get('self_test', [])) + 1)]
    if args.only_stale:
        changed = set(stale_items(read_json(args.only_stale), notes, run)[0])
        new_top = {r for r in refs if r == 'map' or re.fullmatch(r's\d+:(takeaway|visual)', r)} - \
            {i['ref'] for i in read_json(args.only_stale).get('precision', {}).get('items', [])}
        refs = sorted(changed | new_top)
    if args.light:
        refs = [r for r in refs if is_top(r)]
    # Self-test answers are checked against the section they point back to.
    quiz_section = {f'q{j}': t.get('section') for j, t in enumerate(notes.get('self_test', []), 1)}
    sections = {}
    for i, s in enumerate(notes['sections'], 1):
        mine = [r for r in refs if r.startswith(f's{i}:') or quiz_section.get(r) == i]
        if not mine:
            continue
        frames = sorted({s['frames'][int(r.split(':f')[1])]['path'] for r in mine if ':f' in r})
        sections[f's{i}'] = {'title': s['title'], 'time': f"{stamp(s['start'])}-{stamp(s['end'])}",
                             'transcript': [f"[{x} {stamp(rows[x]['start'])}] {rows[x]['text']}" for x in s['source_ids'] if x in rows],
                             'frames_to_check': [str(run / f) for f in frames]}
    items = []
    for r in refs:
        sec = re.match(r's(\d+):', r)
        context = f's{sec[1]}' if sec else (f's{quiz_section[r]}' if quiz_section.get(r) else 'all sections' if args.light else 'transcript.txt')
        items.append({'ref': r, 'hash': hashes[r], 'context': context, 'text': unit_text(notes, r, run)})
    write(out / 'precision/items.json', dump({'mode': 'light' if args.light else 'full', 'sections': sections, 'items': items}) + '\n')
    if args.light:
        # Every section has a takeaway, so `sections` already carries the whole transcript; no frames, no recall packets.
        write(out / 'precision/PROMPT.md', LIGHT_PROMPT)
        write(out / 'RUN.md', LIGHT_RUN_MD.format(dir=out, notes=notes_path))
        print(dump({'packets': str(out), 'mode': 'light', 'precision_items': len(items),
                    'next': 'Run precision/ once with a different model family than the writer; see RUN.md'}))
        return
    write(out / 'precision/PROMPT.md', PRECISION_PROMPT)
    lines = [f"[{x['id']} {stamp(x['start'])}] {x['text']}" for x in sorted(rows.values(), key=lambda r: r['start'])]
    write(out / 'author/transcript.txt', '\n'.join(lines) + '\n')
    write(out / 'precision/transcript.txt', '\n'.join(lines) + '\n')
    frames_dir = run / 'frames'
    write(out / 'author/PROMPT.md', AUTHOR_PROMPT.format(n=args.questions, frames=frames_dir if frames_dir.exists() else 'none (text-only run)'))
    write(out / 'author/GRADE.md', GRADE_PROMPT)
    write(out / 'answer/notes.txt', flatten(notes, run))
    write(out / 'answer/PROMPT.md', ANSWER_PROMPT)
    write(out / 'RUN.md', RUN_MD.format(dir=out, notes=notes_path))
    print(dump({'packets': str(out), 'precision_items': len(items), 'sections_with_context': len(sections),
                'next': 'Run the author and precision packets with a different model family than the writer; see RUN.md'}))


MAX_POINT_CHARS = 160


def question_problems(qs):
    """Questions that break the author contract: one topic, 1-3 short key points."""
    bad = []
    for q in qs:
        pts = q.get('expected')
        if not isinstance(pts, list) or not 1 <= len(pts) <= 3 or not all(isinstance(x, str) and 0 < len(x) <= MAX_POINT_CHARS for x in pts):
            bad.append(q.get('id', '?'))
    return bad


def blind(args):
    d = safe_path(args.dir)
    qs = read_json(d / 'author/questions.json')
    qs = qs.get('questions', qs) if isinstance(qs, dict) else qs
    write(d / 'answer/questions-blind.json', dump([{'id': q['id'], 'question': q['question']} for q in qs]) + '\n')
    print(dump({'questions': len(qs), 'output': str(d / 'answer/questions-blind.json')}))


def merge(args):
    """Fold returned packets into fidelity-eval.json; with --update only the re-judged items are replaced."""
    notes_path, d = safe_path(args.notes), safe_path(args.dir)
    notes, run = read_json(notes_path), notes_path.parent
    hashes = item_hashes(notes, run)
    old = read_json(args.update) if args.update else {}
    precision, recall = dict(old.get('precision', {})), dict(old.get('recall', {}))
    packet = d / 'precision/items.json'
    mode = old.get('mode', 'full') if args.update else (read_json(packet).get('mode', 'full') if packet.exists() else 'full')
    if (d / 'precision/results.json').exists():
        res = read_json(d / 'precision/results.json')
        new = {i['ref']: dict(i, hash=hashes.get(i['ref'])) for i in (res.get('items', res) if isinstance(res, dict) else res)}
        precision.update(items=[i for i in precision.get('items', []) if i['ref'] not in new] + list(new.values()),
                         reviewer=role(args.reviewer_model, args.writer_model), reviewer_model=args.reviewer_model,
                         method=precision.get('method', 'prepare --light: all takeaways/explainers + map' if mode == 'light' else
                                              'prepare packets: all takeaways/explainers + per-section sample') + f'; {len(new)} judged in latest round')
    if (d / 'author/questions.json').exists():
        qs = read_json(d / 'author/questions.json')
        qs = qs.get('questions', qs) if isinstance(qs, dict) else qs
        ans = {a['id']: a for a in read_json(d / 'answer/answers.json')}
        grades = {g['id']: g for g in read_json(d / 'author/grades.json')}
        new = {}
        for q in qs:
            a, g = ans.get(q['id'], {}), grades.get(q['id'], {})
            new[q['id']] = {**q, 'answer': a.get('answer', ''), 'found_in': a.get('found_in'), 'verdict': g.get('verdict'),
                            'note': g.get('note', ''), 'hash': scope_hash(hashes, a.get('found_in'))}
        recall.update(items=[i for i in recall.get('items', []) if i['id'] not in new] + list(new.values()),
                      question_author=role(args.author_model, args.writer_model), answerer=role(args.answerer_model, args.writer_model),
                      author_model=args.author_model, answerer_model=args.answerer_model)
    report = {'schema_version': 1, 'mode': mode, 'notes_sha256': hashlib.sha256(notes_path.read_bytes()).hexdigest(),
              'writer_model': args.writer_model, 'precision': precision, 'recall': recall}
    write(args.out, dump(report) + '\n')
    print(dump(score(report, notes)))


def stale(args):
    notes_path = safe_path(args.notes)
    report, notes = read_json(args.eval), read_json(notes_path)
    if not per_item_bound(report):
        raise ValueError('This eval has no per-item hashes (legacy); rerun it once with prepare/merge')
    p, r = stale_items(report, notes, notes_path.parent)
    print(dump({'stale_precision': p, 'stale_recall': r,
                'next': 'prepare --only-stale EVAL builds a delta precision packet; re-answer and re-grade only these recall ids; then merge --update EVAL'}))


def score_cmd(args):
    notes_path = safe_path(args.notes)
    report, notes = read_json(args.eval), read_json(notes_path)
    if per_item_bound(report):
        p, r = stale_items(report, notes, notes_path.parent)
        if p or r:
            print(dump({'status': 'stale', 'stale_precision': p, 'stale_recall': r,
                        'next': 'Re-review only these items: stale / prepare --only-stale / merge --update'}))
            return 2
    elif report.get('notes_sha256') != hashlib.sha256(notes_path.read_bytes()).hexdigest():
        raise ValueError('Eval is bound to a different notes.json; rerun it on the current notes')
    result = score(report, notes, {k: getattr(args, k) for k in DEFAULTS})
    if report.get('writer_model'):
        result['writer_model'] = report['writer_model']
    print(dump(result))
    from course_notes import log_stage
    log_stage(notes_path.parent, 'fidelity_eval', 'failed' if result['status'] == 'failed' else 'completed',
              f"{result['status']}: precision {result['precision']}, recall {result['recall']}", str(safe_path(args.eval)))
    if args.ledger:
        record(args, notes_path.parent, report, result)
    return 2 if result['status'] == 'failed' else 0


def record(args, run, report, result):
    """Upsert this run's latest score into the course ledger, so rescoring after fixes replaces the entry."""
    if not (args.skill_version and args.source_type and report.get('writer_model')):
        raise ValueError('Recording in the ledger needs --skill-version, --source-type and an eval with writer_model')
    path = safe_path(args.ledger)
    ledger = read_json(path) if path.exists() else {'schema_version': 1, 'entries': []}
    entry = {'at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'run': str(run),
             'writer_model': model_id(report['writer_model']), 'skill_version': args.skill_version, 'source_type': args.source_type,
             'mode': result.get('mode', 'full'), 'status': result['status'],
             'precision': result['precision'], 'recall': result['recall']}
    ledger['entries'] = [e for e in ledger['entries'] if e['run'] != entry['run']] + [entry]
    write(path, dump(ledger) + '\n')


def model_id(name):
    """'Grok 4.7-High' and 'grok-4.7-high' are the same ledger key."""
    return re.sub(r'\s+', '-', (name or '').strip().lower())


def decide(entries, writer, skill_version, source_type, every=AUDIT_EVERY):
    """Full eval to approve a new combination, every `every`th lesson, and until a failed audit passes again."""
    combo = 'this writer model + skill version + source type'
    key = (model_id(writer), skill_version, source_type)
    mine = sorted((e for e in entries if (model_id(e['writer_model']), e['skill_version'], e['source_type']) == key),
                  key=lambda e: e['at'])
    full = [i for i, e in enumerate(mine) if e['mode'] == 'full']
    if not full:
        return {'mode': 'full', 'reason': f'approval: no full eval yet for {combo}'}
    last = mine[full[-1]]
    if last['status'] != 'passed':
        passed = [i for i in full if mine[i]['status'] == 'passed']
        since = mine[passed[-1] + 1:] if passed else mine
        return {'mode': 'full', 'reason': f"latest full eval ({last['run']}) is {last['status']}; stay on full evals until one passes",
                'backfill': [e['run'] for e in since if e['mode'] == 'light']}
    light = sum(1 for e in mine[full[-1] + 1:] if e['mode'] == 'light')
    if light >= every - 1:
        return {'mode': 'full', 'reason': f'audit: {light} light-checked lessons since the latest full eval (every {every}th is full)'}
    return {'mode': 'light', 'reason': f'{combo} passed a full eval; {light} light-checked lessons since',
            'latest_full': {k: last[k] for k in ('run', 'at', 'precision', 'recall')}}


def mode_cmd(args):
    path = safe_path(args.ledger)
    entries = read_json(path)['entries'] if path.exists() else []
    print(dump(decide(entries, args.writer_model, args.skill_version, args.source_type, args.every)))


def skill_version():
    """Short git commit of this skill, so ledger entries need no hand-typed version."""
    here = Path(__file__).resolve().parent
    try:
        out = subprocess.run(['git', '-C', str(here), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(['git', '-C', str(here), 'status', '--porcelain', '--', '.'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode:
        return None
    return out.stdout.strip() + ('-dirty' if dirty.stdout.strip() else '')


def reviewer_cli(writer, choice):
    if choice != 'auto':
        return choice
    return 'cursor' if family(writer) == 'gpt' else 'codex'


def run_role(cli, model, workdir, prompt_file, log, timeout):
    """One fresh reviewer process with the packet folder as workspace; returns token usage from its event stream."""
    prompt = f'Read {prompt_file} in this folder and follow it exactly. Write only the output file it names, in this folder.'
    if cli == 'codex':
        cmd = ['codex', 'exec', '--skip-git-repo-check', '-m', model, '-s', 'workspace-write', '--json', '-C', str(workdir), prompt]
    else:
        cmd = ['cursor-agent', '-p', '--trust', '--sandbox', 'enabled', '--model', model, '--output-format', 'stream-json',
               '--workspace', str(workdir), prompt]
    with open(log, 'w', encoding='utf-8') as fh:
        subprocess.run(cmd, cwd=workdir, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout)
    usage = None
    for line in Path(log).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get('type') in ('turn.completed', 'result') and e.get('usage'):
            usage = e['usage']
    return usage


def review(args):
    """Run every packet that has no output yet (resumable), validate outputs, record tokens, then merge."""
    d, notes_path = safe_path(args.dir), safe_path(args.notes)
    cli = reviewer_cli(args.writer_model, args.reviewer)
    model = args.reviewer_model or REVIEWERS[cli]
    if family(model) == family(args.writer_model):
        raise ValueError(f'{model} is the same family as the writer {args.writer_model}; pick the other CLI with --reviewer')
    packet = read_json(d / 'precision/items.json') if (d / 'precision/items.json').exists() else {}
    if not args.update and packet.get('mode') != 'light' and not (d / 'author/PROMPT.md').exists():
        raise ValueError(f'{d} has no recall packet, so it cannot stand alone as a full eval; '
                         'pass --update <run>/fidelity-eval.json to fold it into the existing eval')
    skip = set()
    if args.update and (d / 'author/PROMPT.md').exists() and not (d / 'author/questions.json').exists():
        # Incremental round: re-ask only the stale questions instead of authoring new ones.
        old = read_json(args.update)
        ids = set(stale_items(old, read_json(notes_path), notes_path.parent)[1])
        keep = [{k: v for k, v in q.items() if k in ('id', 'question', 'expected', 'evidence', 'from')}
                for q in (old.get('recall') or {}).get('items', []) if q['id'] in ids]
        if keep:
            write(d / 'author/questions.json', dump(keep) + '\n')
        else:
            skip = {'author', 'answer', 'grade'}
    usage_path = d / 'usage.json'
    usage = read_json(usage_path) if usage_path.exists() else {}
    errors = []

    def step(name):
        folder, prompt_file, output = STEPS[name]
        if name in skip or not (d / folder / prompt_file).exists() or (d / output).exists():
            return
        for attempt in (1, 2):
            started = dt.datetime.now(dt.timezone.utc)
            try:
                tokens = run_role(cli, model, d / folder, prompt_file, d / folder / f'{name}.log', args.timeout)
            except subprocess.TimeoutExpired:
                tokens = None
            ok = (d / output).exists()
            if ok:
                try:
                    data = read_json(d / output)
                    if name == 'author' and question_problems(data.get('questions', data) if isinstance(data, dict) else data):
                        raise ValueError('questions break the 1-3 short key points contract')
                except ValueError:
                    (d / output).unlink()
                    ok = False
            usage[name] = {'cli': cli, 'model': model, 'attempts': attempt, 'tokens': tokens,
                           'seconds': round((dt.datetime.now(dt.timezone.utc) - started).total_seconds())}
            if ok:
                return
        errors.append(f'{name}: no valid {output} after 2 attempts; see {d / folder / (name + ".log")}')

    threads = [threading.Thread(target=step, args=(n,)) for n in ('precision', 'author')]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if (d / 'author/questions.json').exists() and (d / 'answer/PROMPT.md').exists():
        blind(SimpleNamespace(dir=d))
        step('answer')
        step('grade')
    write(usage_path, dump(usage) + '\n')
    if errors:
        raise ValueError('; '.join(errors))
    recall = (d / 'author/questions.json').exists()
    merge(SimpleNamespace(notes=notes_path, dir=d, out=args.out, update=args.update, writer_model=args.writer_model,
                          reviewer_model=model, author_model=model if recall else None, answerer_model=model if recall else None))


PRECISION_PROMPT = """# Precision review (packet: items.json)

You check classroom notes against the lecture. You did not write them. Read only items.json and transcript.txt
in this folder and the image files listed under frames_to_check. Each item's `context` names the section in
`sections` whose transcript lines and frames to judge it against; items whose context is transcript.txt
(course map, summary, self-test without a section) are checked against the full transcript. Judge each `text`:

- supported: fully backed by the transcript/frames
- partial: partly backed, strength or tone changed, or editor inference presented as the lecturer's words
- unsupported: nothing in the evidence backs it
- distorted: contradicts the evidence

Write results.json in this folder: [{"ref": "...", "verdict": "...", "evidence": "sentence ids or frame file", "note": "..."}]
Keep each `ref` exactly as given. Do not open notes.json, the HTML page, or files outside this folder.
"""
LIGHT_PROMPT = """# Light precision review (packet: items.json)

You check the top layer of classroom notes (section takeaways, explainer cards, course map) against the lecture.
You did not write them. Read only items.json in this folder. Each item's `context` names the section in `sections`
whose transcript lines to judge it against; the course map (`all sections`) is judged against every section.
Explainer text is given as its labels; check each claim and each arrow or comparison it implies. Judge each `text`:

- supported: fully backed by the transcript
- partial: partly backed, a condition dropped, or strength or tone changed
- unsupported: nothing in the transcript backs it
- distorted: contradicts the transcript (reversed direction, cause and effect swapped, wrong number)

Write results.json in this folder: [{"ref": "...", "verdict": "...", "evidence": "sentence ids", "note": "..."}]
Keep each `ref` exactly as given. Do not open notes.json, the HTML page, or files outside this folder.
"""
AUTHOR_PROMPT = """# Recall question author

Write recall questions from the lecture itself. Use only transcript.txt in this folder and the frames in: {frames}
(look at sheet-*.jpg contact sheets first if present). Do not open notes.json or any HTML page.

Write at least {n} questions covering beginning, middle and end; test definitions, conditions, numbers, cases,
the lecturer's explicit positions and Q&A. At least 3 must be answerable only from frames (code, numbers, slides).
Write questions.json here: [{{"id": "q01", "question": "...", "expected": ["key point", "..."], "evidence": "sentence ids or frame file", "from": "transcript|visual"}}]
Each question asks about one thing. `expected` lists 1-3 key points, each one short fact (at most ~25 words);
split a question that needs more into several questions. Grading checks exactly these points, so do not list
details you would not fail an answer for.
You will grade answers later with GRADE.md.
"""
ANSWER_PROMPT = """# Recall answerer

Answer each question in questions-blind.json using only notes.txt in this folder; no outside knowledge.
Write answers.json here: [{"id": "q01", "answer": "...", "found_in": "ref labels from notes.txt such as s3:p1, or null if not in the notes"}]
"""
GRADE_PROMPT = """# Grade recall answers

Compare ../answer/answers.json with your questions.json. For each id judge against the listed `expected` points
only: correct (every point present, any wording), partial (some points), missing (not found), wrong (contradicts
a point). Details outside the listed points never lower a grade. Write grades.json here: [{"id": "q01", "verdict": "...", "note": "..."}]
"""
RUN_MD = """# Fidelity eval with external models

Packets: {dir}. Use a model family different from the writer's: merge records every model and downgrades
same-family review to self_checked. Each packet is self-contained, so reviewers need no other context.

Normally one command does all of the steps below:
   python3 fidelity_eval.py review --notes {notes} --dir {dir} --out <run>/fidelity-eval.json --writer-model <writer>

Manual steps, only if `review` cannot run here:
1. In parallel, as fresh processes with the packet folder as workspace, for example:
   codex exec -m gpt-6.1-sol -s workspace-write --skip-git-repo-check -C {dir}/author "$(cat {dir}/author/PROMPT.md)"
   cursor-agent -p --force --trust --model grok-4.7-high --workspace {dir}/precision "$(cat {dir}/precision/PROMPT.md)"
2. python3 fidelity_eval.py blind --dir {dir}
3. Answerer (a model that has not seen questions.json), workspace {dir}/answer, prompt answer/PROMPT.md
4. Grading by the author model, workspace {dir}/author, prompt author/GRADE.md
5. python3 fidelity_eval.py merge --notes {notes} --dir {dir} --out <run>/fidelity-eval.json \\
     --writer-model <writer> --reviewer-model <precision model> --author-model <author model> --answerer-model <answerer model>

After editing notes do not rerun everything: `stale` lists changed items, `prepare --only-stale <eval>` builds a
delta precision packet, re-answer and re-grade only the stale recall ids, then `merge --update <run>/fidelity-eval.json`.
"""
LIGHT_RUN_MD = """# Light fidelity check (production)

Packet: {dir}/precision. One reviewer, one run, a model family different from the writer's. Normally:
   python3 fidelity_eval.py review --notes {notes} --dir {dir} --out <run>/fidelity-eval.json --writer-model <writer>
Manual equivalent, for example:
   codex exec -m gpt-6.1-sol -s workspace-write --skip-git-repo-check -C {dir}/precision "$(cat {dir}/precision/PROMPT.md)"
   cursor-agent -p --force --trust --model grok-4.7-high --workspace {dir}/precision "$(cat {dir}/precision/PROMPT.md)"
Then:
   python3 fidelity_eval.py merge --notes {notes} --dir {dir} --out <run>/fidelity-eval.json --writer-model <writer> --reviewer-model <reviewer>
   python3 fidelity_eval.py score --notes {notes} --eval <run>/fidelity-eval.json --ledger <ledger> --skill-version <v> --source-type <type>

Any unsupported or distorted item fails: fix the notes, then `prepare --light --only-stale <run>/fidelity-eval.json`
and `merge --update`. Partial items may ship; list them in known_gaps.
"""


def main():
    argv = sys.argv[1:]
    if not argv or argv[0].startswith('-'):
        argv = ['score'] + argv  # pre-subcommand usage: --notes N --eval E
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sc = sub.add_parser('score'); sc.add_argument('--notes', required=True); sc.add_argument('--eval', required=True)
    for key, value in DEFAULTS.items():
        sc.add_argument('--' + key.replace('_', '-'), type=type(value), default=value)
    sc.add_argument('--ledger'); sc.add_argument('--source-type')
    sc.add_argument('--skill-version', default=skill_version(), help='default: git commit of this skill')
    pr = sub.add_parser('prepare'); pr.add_argument('--notes', required=True); pr.add_argument('--index', required=True)
    pr.add_argument('--out', required=True); pr.add_argument('--per-section', type=int, default=2); pr.add_argument('--seed', type=int, default=0)
    pr.add_argument('--questions', type=int, default=DEFAULTS['min_questions']); pr.add_argument('--only-stale', metavar='EVAL')
    pr.add_argument('--light', action='store_true', help='top-layer precision packet only (production)')
    bl = sub.add_parser('blind'); bl.add_argument('--dir', required=True)
    mg = sub.add_parser('merge'); mg.add_argument('--notes', required=True); mg.add_argument('--dir', required=True); mg.add_argument('--out', required=True)
    mg.add_argument('--update', metavar='EVAL'); mg.add_argument('--writer-model', required=True)
    for flag in ('--reviewer-model', '--author-model', '--answerer-model'):
        mg.add_argument(flag)
    st = sub.add_parser('stale'); st.add_argument('--notes', required=True); st.add_argument('--eval', required=True)
    md = sub.add_parser('mode'); md.add_argument('--ledger', required=True); md.add_argument('--writer-model', required=True)
    md.add_argument('--skill-version', default=skill_version(), help='default: git commit of this skill')
    md.add_argument('--source-type', required=True)
    md.add_argument('--every', type=int, default=AUDIT_EVERY)
    rv = sub.add_parser('review'); rv.add_argument('--notes', required=True); rv.add_argument('--dir', required=True)
    rv.add_argument('--out', required=True); rv.add_argument('--writer-model', required=True); rv.add_argument('--update', metavar='EVAL')
    rv.add_argument('--reviewer', choices=['auto', 'codex', 'cursor'], default='auto', help='auto: the CLI of the other family')
    rv.add_argument('--reviewer-model'); rv.add_argument('--timeout', type=int, default=3600, help='seconds per reviewer process')
    args = parser.parse_args(argv)
    try:
        code = {'score': score_cmd, 'prepare': prepare, 'blind': blind, 'merge': merge, 'stale': stale, 'mode': mode_cmd, 'review': review}[args.command](args)
        if code:
            parser.exit(code)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
