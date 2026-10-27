import json
from pathlib import Path
import tempfile
import unittest

from trace_artifacts import capture, check


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('transcript', 'notes', 'html', 'review', 'unrelated'):
            (self.root / name).write_text(name)
        self.spec = self.root / 'spec.json'
        self.out = self.root / 'snapshot.json'
        self.data = {'schema_version': 1, 'run_id': 'test', 'basis': 'observed_build',
                     'artifacts': [
                         {'id': 'source', 'path': 'transcript', 'depends_on': []},
                         {'id': 'notes', 'path': 'notes', 'depends_on': ['source']},
                         {'id': 'html', 'path': 'html', 'depends_on': ['notes']},
                         {'id': 'review', 'path': 'review', 'depends_on': ['html']},
                         {'id': 'other', 'path': 'unrelated', 'depends_on': []}]}

    def seal(self):
        self.spec.write_text(json.dumps(self.data))
        return capture(self.spec, self.out)

    def test_transitive_invalidation_and_unchanged_output(self):
        self.seal()
        self.assertEqual(check(self.out)['status'], 'unchanged')
        (self.root / 'transcript').write_text('correction')
        result = check(self.out)
        self.assertEqual(result['changed_files'], ['source'])
        self.assertEqual(result['requires_revalidation'], ['html', 'notes', 'review'])
        self.assertEqual((self.root / 'html').read_text(), 'html')

    def test_missing_is_not_pass(self):
        self.seal()
        (self.root / 'notes').unlink()
        result = check(self.out)
        self.assertEqual(result['unavailable_files'], ['notes'])
        self.assertEqual(result['requires_revalidation'], ['html', 'review'])

    def test_cannot_replace_old_snapshot(self):
        self.seal()
        before = self.out.read_bytes()
        with self.assertRaises(ValueError):
            self.seal()
        self.assertEqual(self.out.read_bytes(), before)

    def test_missing_dependency_and_cycle_rejected(self):
        for deps in (['absent'], ['review']):
            self.data['artifacts'][0]['depends_on'] = deps
            with self.assertRaises(ValueError):
                self.seal()
            self.assertFalse(self.out.exists())

    def test_bcut_and_duplicate_paths_rejected(self):
        for path in ('private.bcut/source', 'notes'):
            self.data['artifacts'][0]['path'] = path
            with self.assertRaises(ValueError):
                self.seal()

    def test_historical_remains_historical(self):
        self.data['basis'] = 'historical_inventory'
        self.seal()
        result = check(self.out)
        self.assertEqual(result['basis'], 'historical_inventory')
        self.assertIn('does not mean', result['claim'])

    def test_explicit_relocation(self):
        self.seal()
        snapshot = json.loads(self.out.read_text())
        snapshot['root'] = '/missing-original-root'
        self.out.write_text(json.dumps(snapshot))
        self.assertEqual(check(self.out, self.root)['status'], 'unchanged')

