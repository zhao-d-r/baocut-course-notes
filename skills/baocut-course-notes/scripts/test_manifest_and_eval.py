import contextlib
import copy
import hashlib
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as Args
import unittest
import course_notes as c
import fidelity_eval as fe
import manifest as m
from test_layered import v3_notes


def eval_report(notes, notes_bytes, questions=20):
    p_items = [{'ref': 'map', 'verdict': 'supported', 'evidence': 'all sections'}]
    for i, s in enumerate(notes['sections'], 1):
        p_items.append({'ref': f's{i}:takeaway', 'verdict': 'supported', 'evidence': f's{i} p0'})
        if s.get('visual'):
            p_items.append({'ref': f's{i}:visual', 'verdict': 'supported', 'evidence': f's{i} p0'})
    r_items = [{'id': f'q{n}', 'from': 'visual' if n == 1 else 'transcript', 'question': '问', 'expected': '答',
                'evidence': 'a', 'answer': '答', 'verdict': 'correct', 'found_in': 's1'} for n in range(1, questions + 1)]
    return {'schema_version': 1, 'notes_sha256': hashlib.sha256(notes_bytes).hexdigest(),
            'precision': {'reviewer': 'independent_agent', 'method': 'all top layer + sample', 'items': p_items},
            'recall': {'question_author': 'independent_agent', 'answerer': 'independent_agent', 'items': r_items}}


class EvalTest(unittest.TestCase):
    def setUp(self):
        self.notes = v3_notes()
        self.report = eval_report(self.notes, b'{}')

    def test_passes_with_independent_reviewers(self):
        self.assertEqual(fe.score(self.report, self.notes)['status'], 'passed')

    def test_same_agent_is_only_self_checked(self):
        self.report['precision']['reviewer'] = 'same_agent'
        self.assertEqual(fe.score(self.report, self.notes)['status'], 'self_checked')

    def test_every_takeaway_and_visual_must_be_checked(self):
        self.report['precision']['items'] = [i for i in self.report['precision']['items'] if i['ref'] != 's1:visual']
        result = fe.score(self.report, self.notes)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('s1:visual', ' '.join(result['problems']))

    def test_distorted_top_layer_fails_even_with_high_average(self):
        self.report['precision']['items'] += [{'ref': 's1:p0', 'verdict': 'supported', 'evidence': 'a'}] * 60
        self.report['precision']['items'][1]['verdict'] = 'distorted'
        self.assertEqual(fe.score(self.report, self.notes)['status'], 'failed')

    def test_recall_threshold_and_visual_questions(self):
        for item in self.report['recall']['items'][:4]:
            item['verdict'] = 'missing'
        result = fe.score(self.report, self.notes)
        self.assertEqual(result['recall'], 0.8)
        self.assertEqual(result['status'], 'failed')
        report = eval_report(self.notes, b'{}')
        for item in report['recall']['items']:
            item['from'] = 'transcript'
        self.assertIn('visuals', ' '.join(fe.score(report, self.notes)['problems']))

    def test_unknown_ref_rejected(self):
        self.report['precision']['items'].append({'ref': 's9:p0', 'verdict': 'supported', 'evidence': 'x'})
        with self.assertRaisesRegex(ValueError, 'unknown ref'):
            fe.score(self.report, self.notes)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        self.notes = v3_notes()
        (self.run / 'transcript.json').write_text('{"sentences": []}', encoding='utf-8')
        self.write_notes()
        (self.run / 'notes.html').write_text('<html>', encoding='utf-8')
        manifest = {'schema_version': 1, 'run_id': 'demo-run', 'status': {'outcome': 'completed', 'known_gaps': []},
                    'artifacts': [
                        {'id': 'transcript', 'path': 'transcript.json', 'depends_on': [], 'role': 'source', 'origin': 'reused', 'basis': 'same video id'},
                        {'id': 'notes', 'path': 'notes.json', 'depends_on': ['transcript']},
                        {'id': 'html', 'path': 'notes.html', 'depends_on': ['notes']},
                        {'id': 'fidelity_eval', 'path': 'eval.json', 'depends_on': ['notes', 'transcript']}],
                    'issues': []}
        c.write(self.run / 'manifest.json', json.dumps(manifest))

    def tearDown(self):
        self.tmp.cleanup()

    def write_notes(self):
        data = json.dumps(self.notes, ensure_ascii=False).encode('utf-8')
        (self.run / 'notes.json').write_bytes(data)
        (self.run / 'eval.json').write_text(json.dumps(eval_report(self.notes, data)), encoding='utf-8')

    def call(self, fn, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(Args(run=self.run, **kw))

    def manifest(self):
        return json.loads((self.run / 'manifest.json').read_text(encoding='utf-8'))

    def test_log_freeze_check_cycle(self):
        self.call(m.log, stage='asr', status='reused', detail='fresh transcript', evidence=None, attempt=None, job_id=None, occurred_at=None)
        rev = self.call(m.freeze, reason='first delivery', delivered=True)
        self.assertEqual(rev['eval']['status'], 'passed')
        self.assertEqual(self.call(m.check, root=None)['status'], 'unchanged')
        (self.run / 'transcript.json').write_text('{"sentences": [1]}', encoding='utf-8')
        result = self.call(m.check, root=None)
        self.assertEqual(result['changed_files'], ['transcript'])
        self.assertEqual(result['requires_revalidation'], ['fidelity_eval', 'html', 'notes'])
        self.assertEqual(len(self.manifest()['log']), 1)

    def test_stale_eval_blocks_freeze(self):
        self.notes['sections'][0]['takeaway'] = '改过的结论。'
        (self.run / 'notes.json').write_text(json.dumps(self.notes, ensure_ascii=False), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.call(m.freeze, reason='edited', delivered=False)

    def test_history_edit_is_detected(self):
        self.call(m.freeze, reason='r1', delivered=False)
        self.call(m.freeze, reason='r2', delivered=False)
        data = self.manifest()
        data['revisions'][0]['reason'] = 'rewritten'
        c.write(self.run / 'manifest.json', json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'edited'):
            self.call(m.check, root=None)

    def test_issues_cannot_vanish_and_block_completed_delivery(self):
        data = self.manifest()
        data['issues'] = [{'id': 'i1', 'severity': 'high', 'problem': '数字错', 'evidence': 's-1', 'status': 'open'}]
        c.write(self.run / 'manifest.json', json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'block'):
            self.call(m.freeze, reason='deliver', delivered=True)
        self.call(m.freeze, reason='snapshot with open issue', delivered=False)
        data = self.manifest()
        data['issues'] = []
        c.write(self.run / 'manifest.json', json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'disappear'):
            self.call(m.freeze, reason='hide', delivered=False)

    def test_fixed_issue_needs_verification(self):
        data = self.manifest()
        data['issues'] = [{'id': 'i1', 'severity': 'low', 'problem': 'p', 'evidence': 'e', 'status': 'fixed', 'fix': 'f'}]
        c.write(self.run / 'manifest.json', json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'verified_by'):
            self.call(m.freeze, reason='x', delivered=False)


if __name__ == '__main__':
    unittest.main()
