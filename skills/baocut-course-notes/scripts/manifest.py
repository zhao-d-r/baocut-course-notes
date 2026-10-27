#!/usr/bin/env python3
"""One manifest.json per run: sources, dependency graph, stage log, issues and frozen revisions.

Replaces run.json + events.jsonl + trace-spec.json + trace-rNN.json + review.json.
Revisions are append-only and hash-chained, so an overwritten history is detected by `check`.
It never certifies content quality; fidelity lives in the eval file it freezes.
"""
import argparse
import datetime as dt
import hashlib
import json

from course_notes import dump, read_json, safe_path, write

STATUSES = ('started', 'completed', 'failed', 'paused', 'reused')
SEVERITIES = ('high', 'medium', 'low')
ISSUE_STATES = ('open', 'fixed', 'wont_fix')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def chain_hash(revision):
    return hashlib.sha256(json.dumps(revision, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def load(run):
    path = safe_path(run) / 'manifest.json'
    data = read_json(path)
    if data.get('schema_version') != 1 or not isinstance(data.get('run_id'), str) or not data['run_id']:
        raise ValueError('manifest.json needs schema_version 1 and run_id')
    for key in ('artifacts', 'log', 'issues', 'revisions'):
        data.setdefault(key, [])
    return path, data


def graph(items):
    by_id = {}
    for item in items:
        ident = item.get('id')
        if not isinstance(ident, str) or not ident or ident in by_id:
            raise ValueError('Artifact IDs must be unique nonempty strings')
        if not isinstance(item.get('path'), str) or not item['path']:
            raise ValueError('Each artifact needs a path')
        deps = item.get('depends_on')
        if not isinstance(deps, list) or len(set(deps)) != len(deps) or any(not isinstance(x, str) for x in deps):
            raise ValueError('Explicit depends_on list required, including [] for sources: ' + ident)
        by_id[ident] = item
    visiting, done = set(), set()

    def visit(ident):
        if ident not in by_id:
            raise ValueError('Unknown dependency: ' + ident)
        if ident in visiting:
            raise ValueError('Dependency cycle: ' + ident)
        if ident not in done:
            visiting.add(ident)
            for dep in by_id[ident]['depends_on']:
                visit(dep)
            visiting.remove(ident)
            done.add(ident)

    for ident in by_id:
        visit(ident)
    return by_id


def verify_chain(revisions):
    prev = None
    for n, rev in enumerate(revisions, 1):
        if rev.get('rev') != n or rev.get('prev_sha256') != prev:
            raise ValueError(f'Revision history was edited or reordered at rev {n}')
        prev = chain_hash(rev)
    return prev


def check_issues(data):
    for issue in data['issues']:
        for key in ('id', 'problem', 'evidence'):
            if not isinstance(issue.get(key), str) or not issue[key].strip():
                raise ValueError('Issue requires id, problem and evidence')
        if issue.get('severity') not in SEVERITIES or issue.get('status') not in ISSUE_STATES:
            raise ValueError('Invalid issue severity/status: ' + issue['id'])
        if issue['status'] == 'fixed' and not (issue.get('fix') and issue.get('verified_by')):
            raise ValueError('Fixed issue needs fix and verified_by: ' + issue['id'])
    ids = [i['id'] for i in data['issues']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate issue id')
    if data['revisions']:
        vanished = set(data['revisions'][-1].get('issues', {})) - set(ids)
        if vanished:
            raise ValueError('Issues cannot disappear from history: ' + ', '.join(sorted(vanished)))


def log(args):
    path, data = load(args.run)
    if args.status not in STATUSES:
        raise ValueError('Invalid status')
    entry = {'at': now(), 'occurred_at': args.occurred_at, 'stage': args.stage, 'status': args.status,
             'attempt': args.attempt, 'job_id': args.job_id, 'detail': args.detail, 'evidence': args.evidence}
    if args.occurred_at:
        parsed = dt.datetime.fromisoformat(args.occurred_at.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('occurred_at requires a timezone')
        entry['occurred_at'] = parsed.astimezone(dt.timezone.utc).isoformat()
    data['log'].append(entry)
    write(path, dump(data) + '\n')
    return entry


def freeze(args):
    path, data = load(args.run)
    root = path.parent
    by_id = graph(data['artifacts'])
    check_issues(data)
    prev = verify_chain(data['revisions'])
    files = {}
    for ident, item in by_id.items():
        target = safe_path(root / item['path'])
        if target == path:
            raise ValueError('manifest.json cannot list itself')
        files[ident] = {'path': item['path'], **fingerprint(target)}
    evaluation = None
    if 'fidelity_eval' in by_id:
        if 'notes' not in by_id:
            raise ValueError('fidelity_eval needs a notes artifact to bind to')
        report = read_json(root / by_id['fidelity_eval']['path'])
        if report.get('notes_sha256') != files['notes']['sha256']:
            raise ValueError('Fidelity eval is stale: rerun it against the current notes before freezing')
        import fidelity_eval
        evaluation = fidelity_eval.score(report, read_json(root / by_id['notes']['path']))
    if args.delivered:
        if evaluation is None:
            raise ValueError('A delivered revision needs a fidelity_eval artifact bound to the current notes')
        if not isinstance(data.get('status'), dict) or data['status'].get('outcome') not in ('completed', 'partial', 'failed'):
            raise ValueError('Set status.outcome before delivering')
        blocking = [i['id'] for i in data['issues'] if i['status'] == 'open' and i['severity'] == 'high']
        if blocking and data['status']['outcome'] == 'completed':
            raise ValueError('Open high-severity issues block a completed delivery: ' + ', '.join(blocking))
    revision = {'rev': len(data['revisions']) + 1, 'at': now(), 'reason': args.reason, 'delivered': bool(args.delivered),
                'files': files, 'issues': {i['id']: i['status'] for i in data['issues']},
                'outcome': (data.get('status') or {}).get('outcome'), 'eval': evaluation, 'prev_sha256': prev}
    data['revisions'].append(revision)
    write(path, dump(data) + '\n')
    return revision


def check(args):
    path, data = load(args.run)
    root = safe_path(args.root) if args.root else path.parent
    verify_chain(data['revisions'])
    if not data['revisions']:
        raise ValueError('No frozen revision yet')
    latest = data['revisions'][-1]
    by_id = graph([{**a, 'path': latest['files'][a['id']]['path']} for a in data['artifacts'] if a['id'] in latest['files']])
    undeclared = sorted(a['id'] for a in data['artifacts'] if a['id'] not in latest['files'])
    changed, unavailable = [], []
    for ident, rec in latest['files'].items():
        try:
            actual = fingerprint(safe_path(root / rec['path']))
        except OSError:
            unavailable.append(ident)
            continue
        if actual['sha256'] != rec['sha256'] or actual['bytes'] != rec['bytes']:
            changed.append(ident)
    affected = set(changed + unavailable)
    while True:
        grown = affected | {i for i, item in by_id.items() if affected.intersection(item['depends_on'])}
        if grown == affected:
            break
        affected = grown
    return {'run_id': data['run_id'], 'revision': latest['rev'], 'delivered': latest['delivered'],
            'status': 'changed' if affected or undeclared else 'unchanged',
            'changed_files': changed, 'unavailable_files': unavailable, 'not_yet_frozen': undeclared,
            'requires_revalidation': sorted(affected - set(changed + unavailable)),
            'claim': 'Unchanged files do not prove the content is complete or correct; see the frozen eval.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    lg = sub.add_parser('log')
    lg.add_argument('--run', required=True)
    lg.add_argument('--stage', required=True)
    lg.add_argument('--status', choices=STATUSES, required=True)
    lg.add_argument('--detail', default='')
    for flag in ('--evidence', '--attempt', '--job-id', '--occurred-at'):
        lg.add_argument(flag)
    fr = sub.add_parser('freeze')
    fr.add_argument('--run', required=True)
    fr.add_argument('--reason', required=True)
    fr.add_argument('--delivered', action='store_true')
    ch = sub.add_parser('check')
    ch.add_argument('--run', required=True)
    ch.add_argument('--root', help='Explicit relocated run root; never guessed')
    args = parser.parse_args()
    try:
        result = {'log': log, 'freeze': freeze, 'check': check}[args.command](args)
        print(dump(result))
        if args.command == 'check' and result['status'] != 'unchanged':
            parser.exit(2)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
