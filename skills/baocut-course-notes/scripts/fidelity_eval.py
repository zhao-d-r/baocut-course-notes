#!/usr/bin/env python3
"""Fidelity eval: precision (what the notes say is supported) and recall (what the lecture
taught can be answered from the notes). Judgments come from reviewers running a different
model; this script builds their packets, merges their answers and checks binding, coverage
and arithmetic, never the semantics.

  prepare --notes N --index I --out DIR      reviewer packets + RUN.md with external-CLI commands
  blind   --dir DIR                          strip expected answers for the answerer
  merge   --notes N --dir DIR --out EVAL --writer-model M --reviewer-model R --author-model A --answerer-model B
  stale   --notes N --eval EVAL              items whose content changed since review (incremental re-review)
  score   --notes N --eval EVAL              (default when no subcommand is given)
"""
import argparse
import hashlib
import html as htmllib
import random
import re
import sys
from pathlib import Path

from course_notes import dump, read_json, safe_path, stamp, text_of, write
from reading_layout import FIELDS, supplements

PRECISION = {'supported': 1.0, 'partial': 0.5, 'unsupported': 0.0, 'distorted': 0.0}
RECALL = {'correct': 1.0, 'partial': 0.5, 'missing': 0.0, 'wrong': 0.0}
ROLES = ('independent_agent', 'human', 'same_agent')
DEFAULTS = {'min_precision': 0.95, 'min_recall': 0.85, 'min_questions': 20}


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
    recall = report.get('recall') or {}
    r_items = recall.get('items') or []
    for item in r_items:
        for key in ('id', 'question', 'expected', 'evidence'):
            if not isinstance(item.get(key), str) or not item[key].strip():
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
    sections = {}
    for i, s in enumerate(notes['sections'], 1):
        mine = [r for r in refs if r.startswith(f's{i}:')]
        if not mine:
            continue
        frames = sorted({s['frames'][int(r.split(':f')[1])]['path'] for r in mine if ':f' in r})
        sections[f's{i}'] = {'title': s['title'], 'time': f"{stamp(s['start'])}-{stamp(s['end'])}",
                             'transcript': [f"[{x} {stamp(rows[x]['start'])}] {rows[x]['text']}" for x in s['source_ids'] if x in rows],
                             'frames_to_check': [str(run / f) for f in frames]}
    items = [{'ref': r, 'hash': hashes[r], 'text': unit_text(notes, r, run)} for r in refs]
    write(out / 'precision/items.json', dump({'sections': sections, 'items': items}) + '\n')
    write(out / 'precision/PROMPT.md', PRECISION_PROMPT)
    lines = [f"[{x['id']} {stamp(x['start'])}] {x['text']}" for x in sorted(rows.values(), key=lambda r: r['start'])]
    write(out / 'author/transcript.txt', '\n'.join(lines) + '\n')
    frames_dir = run / 'frames'
    write(out / 'author/PROMPT.md', AUTHOR_PROMPT.format(n=args.questions, frames=frames_dir if frames_dir.exists() else 'none (text-only run)'))
    write(out / 'author/GRADE.md', GRADE_PROMPT)
    write(out / 'answer/notes.txt', flatten(notes, run))
    write(out / 'answer/PROMPT.md', ANSWER_PROMPT)
    write(out / 'RUN.md', RUN_MD.format(dir=out, notes=notes_path))
    print(dump({'packets': str(out), 'precision_items': len(items), 'sections_with_context': len(sections),
                'next': 'Run the author and precision packets with a different model family than the writer; see RUN.md'}))


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
    if (d / 'precision/results.json').exists():
        res = read_json(d / 'precision/results.json')
        new = {i['ref']: dict(i, hash=hashes.get(i['ref'])) for i in (res.get('items', res) if isinstance(res, dict) else res)}
        precision.update(items=[i for i in precision.get('items', []) if i['ref'] not in new] + list(new.values()),
                         reviewer=role(args.reviewer_model, args.writer_model), reviewer_model=args.reviewer_model,
                         method=precision.get('method', 'prepare packets: all takeaways/explainers + per-section sample') + f'; {len(new)} judged in latest round')
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
    report = {'schema_version': 1, 'notes_sha256': hashlib.sha256(notes_path.read_bytes()).hexdigest(),
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
    return 2 if result['status'] == 'failed' else 0


PRECISION_PROMPT = """# Precision review (packet: items.json)

You check classroom notes against the lecture. You did not write them. Read only items.json in this folder
and the image files it lists under frames_to_check. Judge each item's `text` against its section's
`transcript` lines and listed frames:

- supported: fully backed by the transcript/frames
- partial: partly backed, strength or tone changed, or editor inference presented as the lecturer's words
- unsupported: nothing in the evidence backs it
- distorted: contradicts the evidence

Write results.json in this folder: [{"ref": "...", "verdict": "...", "evidence": "sentence ids or frame file", "note": "..."}]
Keep each `ref` exactly as given. Do not open notes.json, the HTML page, or files outside this folder.
"""
AUTHOR_PROMPT = """# Recall question author

Write recall questions from the lecture itself. Use only transcript.txt in this folder and the frames in: {frames}
(look at sheet-*.jpg contact sheets first if present). Do not open notes.json or any HTML page.

Write at least {n} questions covering beginning, middle and end; test definitions, conditions, numbers, cases,
the lecturer's explicit positions and Q&A. At least 3 must be answerable only from frames (code, numbers, slides).
Write questions.json here: [{{"id": "q01", "question": "...", "expected": "1-3 gradable key points", "evidence": "sentence ids or frame file", "from": "transcript|visual"}}]
You will grade answers later with GRADE.md.
"""
ANSWER_PROMPT = """# Recall answerer

Answer each question in questions-blind.json using only notes.txt in this folder; no outside knowledge.
Write answers.json here: [{"id": "q01", "answer": "...", "found_in": "ref labels from notes.txt such as s3:p1, or null if not in the notes"}]
"""
GRADE_PROMPT = """# Grade recall answers

Compare ../answer/answers.json with your questions.json. For each id judge: correct (all key points), partial,
missing (not found), wrong (contradicts). Write grades.json here: [{"id": "q01", "verdict": "...", "note": "..."}]
"""
RUN_MD = """# Fidelity eval with external models

Packets: {dir}. Use a model family different from the writer's: merge records every model and downgrades
same-family review to self_checked. Each packet is self-contained, so reviewers need no other context.

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


def main():
    argv = sys.argv[1:]
    if not argv or argv[0].startswith('-'):
        argv = ['score'] + argv  # pre-subcommand usage: --notes N --eval E
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sc = sub.add_parser('score'); sc.add_argument('--notes', required=True); sc.add_argument('--eval', required=True)
    for key, value in DEFAULTS.items():
        sc.add_argument('--' + key.replace('_', '-'), type=type(value), default=value)
    pr = sub.add_parser('prepare'); pr.add_argument('--notes', required=True); pr.add_argument('--index', required=True)
    pr.add_argument('--out', required=True); pr.add_argument('--per-section', type=int, default=2); pr.add_argument('--seed', type=int, default=0)
    pr.add_argument('--questions', type=int, default=DEFAULTS['min_questions']); pr.add_argument('--only-stale', metavar='EVAL')
    bl = sub.add_parser('blind'); bl.add_argument('--dir', required=True)
    mg = sub.add_parser('merge'); mg.add_argument('--notes', required=True); mg.add_argument('--dir', required=True); mg.add_argument('--out', required=True)
    mg.add_argument('--update', metavar='EVAL'); mg.add_argument('--writer-model', required=True)
    for flag in ('--reviewer-model', '--author-model', '--answerer-model'):
        mg.add_argument(flag)
    st = sub.add_parser('stale'); st.add_argument('--notes', required=True); st.add_argument('--eval', required=True)
    args = parser.parse_args(argv)
    try:
        code = {'score': score_cmd, 'prepare': prepare, 'blind': blind, 'merge': merge, 'stale': stale}[args.command](args)
        if code:
            parser.exit(code)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
