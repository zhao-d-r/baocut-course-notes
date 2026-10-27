import contextlib
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as Args
import unittest

import course_notes as c
import fidelity_eval as fe
import svgcard
from test_layered import PNG, SVG, v3_notes

HERE = Path(__file__).resolve().parent


def quiet(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args)
    return result, out.getvalue()


class RunDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        rows = [{'id': 'a', 'start': 0, 'end': 20, 'text': '平均数是总量除以样本数'}, {'id': 'b', 'start': 310, 'end': 330, 'text': '比较前核对单位'}]
        c.write(self.root / 'export.json', json.dumps({'sentences': rows}, ensure_ascii=False))
        quiet(c.chunks, Args(input=self.root / 'export.json', out=self.root / 'chunks'))
        (self.root / 'frame.png').write_bytes(PNG)
        (self.root / 'visuals').mkdir()
        (self.root / 'visuals/map.svg').write_text(SVG, encoding='utf-8')
        (self.root / 'visuals/s1.svg').write_text(SVG, encoding='utf-8')
        self.notes = v3_notes()
        self.index = self.root / 'chunks/index.json'

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, notes=None):
        c.write(self.root / 'notes.json', json.dumps(notes or self.notes, ensure_ascii=False))
        return self.root / 'notes.json'


class ValidateTest(RunDir):
    def test_reports_every_problem_with_paths(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0]['takeaway'] = ''
        notes['sections'][0]['visual']['refs'] = ['p9']
        notes['sections'][1]['source_ids'] = ['zz']
        notes['read_chunks'] = ['chunk-0001']
        result, _ = quiet(c.validate, Args(notes=self.save(notes), index=self.index, layout=None))
        where = {p['where'] for p in result['problems']}
        self.assertEqual(result['status'], 'failed')
        self.assertTrue({'read_chunks', 'sections[0].takeaway', 'sections[0].visual', 'sections[1].source_ids'} <= where, where)

    def test_render_still_raises_the_first_problem(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0]['takeaway'] = ''
        with self.assertRaisesRegex(ValueError, 'takeaway'):
            quiet(c.render, Args(notes=self.save(notes), index=self.index, out=self.root / 'o.html'))

    def test_valid_notes_pass(self):
        result, _ = quiet(c.validate, Args(notes=self.save(), index=self.index, layout=None))
        self.assertEqual(result['status'], 'passed', result['problems'])

    def test_scaffold_is_rejected_until_written(self):
        quiet(c.scaffold, Args(index=self.index, out=self.root / 'draft.json', title=None, source_url=None))
        draft = json.loads((self.root / 'draft.json').read_text(encoding='utf-8'))
        self.assertEqual([s['source_ids'] for s in draft['sections']], [['a'], ['b']])
        self.assertEqual(draft['read_chunks'], [])
        result, _ = quiet(c.validate, Args(notes=self.root / 'draft.json', index=self.index, layout=None))
        self.assertTrue(any('Placeholder' in p['error'] for p in result['problems']))
        with self.assertRaisesRegex(ValueError, 'exists'):
            quiet(c.scaffold, Args(index=self.index, out=self.root / 'draft.json', title=None, source_url=None))

    def test_scripts_log_their_stage_into_manifest(self):
        (self.root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'run_id': 't', 'log': []}), encoding='utf-8')
        quiet(c.render, Args(notes=self.save(), index=self.index, out=self.root / 'o.html'))
        log = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))['log']
        self.assertEqual(log[-1]['stage'], 'render')

    def test_non_utf8_svg_is_named(self):
        (self.root / 'visuals/s1.svg').write_bytes(b'<svg>\xb6\xcf</svg>')  # GBK bytes Cursor once wrote
        result, _ = quiet(c.validate, Args(notes=self.save(), index=self.index, layout=None))
        self.assertTrue(any('UTF-8' in p['error'] for p in result['problems']))


class SvgCardTest(unittest.TestCase):
    def test_card_meets_layout_rules(self):
        spec = {'title': '重试前先确认', 'rows': [{'label': '断网', 'text': '结果未知，这一行足够长需要自动换行显示', 'tag': '§4'},
                                              [{'label': '直接重发', 'tone': 'red'}, {'label': '先查询', 'tone': 'green'}]]}
        svg = svgcard.build_svg(spec)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'c.svg'
            path.write_text(svg, encoding='utf-8')
            self.assertEqual(svgcard.lint_svg(path), [])
        self.assertIn('viewBox="0 0 400', svg)
        self.assertIn('<title>重试前先确认</title>', svg)

    def test_lint_flags_wide_small_and_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.svg'
            path.write_text('<svg viewBox="0 0 600 300"><text font-size="12">x</text><image href="http://e.com/a.png"/></svg>', encoding='utf-8')
            problems = ' '.join(svgcard.lint_svg(path))
        for word in ('600', 'below 16', 'external', 'title'):
            self.assertIn(word, problems)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg not installed')
class FramesTest(unittest.TestCase):
    def test_scan_finds_scene_changes_and_grab_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / 'v.mp4'
            colors = ['red', 'blue', 'green']
            cmd = ['ffmpeg', '-loglevel', 'error']
            for col in colors:
                cmd += ['-f', 'lavfi', '-i', f'color=c={col}:s=160x90:d=2:r=10']
            cmd += ['-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1[v]', '-map', '[v]', str(video)]
            subprocess.run(cmd, check=True)
            run = lambda *a: subprocess.run([sys.executable, '-B', str(HERE / 'frames.py'), *a], capture_output=True, text=True)
            self.assertEqual(run('scan', '--video', str(video), '--out', f'{tmp}/frames', '--interval', '30').returncode, 0)
            report = json.loads((Path(tmp) / 'frames/candidates.json').read_text(encoding='utf-8'))
            self.assertEqual([round(r['time']) for r in report['candidates']], [0, 2, 4])
            self.assertTrue((Path(tmp) / 'frames' / report['sheets'][0]['path']).exists())
            self.assertNotEqual(run('scan', '--video', str(video), '--out', f'{tmp}/frames').returncode, 0)
            out = run('grab', '--video', str(video), '--out', f'{tmp}/frames', '--time', '3.0')
            self.assertEqual(json.loads(out.stdout)['frames'][0]['path'], 'frames/v000003000.jpg')


class CheckHtmlTest(RunDir):
    def test_static_checks_catch_broken_links_and_pass_rendered_page(self):
        quiet(c.render, Args(notes=self.save(), index=self.index, out=self.root / 'page.html'))
        run = lambda: subprocess.run([sys.executable, '-B', str(HERE / 'check_html.py'), str(self.root / 'page.html'), '--no-browser'],
                                     capture_output=True, text=True)
        good = run()
        self.assertEqual(good.returncode, 0, good.stdout)
        self.assertEqual(json.loads(good.stdout)['status'], 'static_only')
        page = (self.root / 'page.html').read_text(encoding='utf-8')
        (self.root / 'page.html').write_text(page.replace('</body>', '<a href="#nowhere">x</a><a href="原文.html">y</a></body>'), encoding='utf-8')
        bad = json.loads(run().stdout)
        self.assertEqual(bad['status'], 'failed')
        self.assertTrue(any('anchors' in p for p in bad['problems']) and any('missing files' in p for p in bad['problems']))


class EvalPipelineTest(RunDir):
    def answer_packets(self, packets, verdict='correct'):
        qs = [{'id': f'q{n:02d}', 'question': '问', 'expected': '答', 'evidence': 'a', 'from': 'visual' if n == 1 else 'transcript'} for n in range(1, 21)]
        c.write(packets / 'author/questions.json', json.dumps(qs))
        quiet(fe.blind, Args(dir=packets))
        blind = json.loads((packets / 'answer/questions-blind.json').read_text(encoding='utf-8'))
        self.assertNotIn('expected', blind[0])
        c.write(packets / 'answer/answers.json', json.dumps([{'id': q['id'], 'answer': '答', 'found_in': 's1:p0'} for q in qs]))
        c.write(packets / 'author/grades.json', json.dumps([{'id': q['id'], 'verdict': verdict} for q in qs]))
        items = json.loads((packets / 'precision/items.json').read_text(encoding='utf-8'))['items']
        c.write(packets / 'precision/results.json', json.dumps([{'ref': i['ref'], 'verdict': 'supported', 'evidence': 'a'} for i in items]))

    def merge(self, packets, **models):
        m = {'writer_model': 'grok-4.7-high', 'reviewer_model': 'gpt-6.1-sol', 'author_model': 'gpt-6.1-sol', 'answerer_model': 'gemini-3.8-flash'}
        m.update(models)
        quiet(fe.merge, Args(notes=self.root / 'notes.json', dir=packets, out=self.root / 'fidelity-eval.json', update=None, **m))
        return json.loads((self.root / 'fidelity-eval.json').read_text(encoding='utf-8'))

    def score(self):
        code, out = quiet(fe.score_cmd, Args(notes=self.root / 'notes.json', eval=self.root / 'fidelity-eval.json', **fe.DEFAULTS))
        return code, json.loads(out)

    def test_packets_merge_score_and_incremental_review(self):
        self.save()
        packets = self.root / 'packets'
        quiet(fe.prepare, Args(notes=self.root / 'notes.json', index=self.index, out=packets, per_section=2, seed=0, questions=20, only_stale=None))
        items = json.loads((packets / 'precision/items.json').read_text(encoding='utf-8'))
        refs = {i['ref'] for i in items['items']}
        self.assertTrue({'map', 's1:takeaway', 's1:visual', 's2:takeaway'} <= refs)
        self.assertIn('平均数是总量除以样本数', ''.join(items['sections']['s1']['transcript']))
        self.assertNotIn('expected', (packets / 'answer/notes.txt').read_text(encoding='utf-8'))
        self.answer_packets(packets)
        self.assertEqual(self.merge(packets)['precision']['reviewer'], 'independent_agent')
        self.assertEqual(self.score(), (0, self.score()[1]))
        self.assertEqual(self.score()[1]['status'], 'passed')
        # Editing one paragraph only stales what depends on it; the rest of the review stands.
        self.notes['sections'][1]['takeaway'] = '先核对样本与单位。'
        self.save()
        code, result = self.score()
        self.assertEqual((code, result['status'], result['stale_precision'], result['stale_recall']), (2, 'stale', ['s2:takeaway'], []))
        delta = self.root / 'delta'
        quiet(fe.prepare, Args(notes=self.root / 'notes.json', index=self.index, out=delta, per_section=2, seed=0, questions=20,
                               only_stale=self.root / 'fidelity-eval.json'))
        self.assertEqual([i['ref'] for i in json.loads((delta / 'precision/items.json').read_text(encoding='utf-8'))['items']], ['s2:takeaway'])
        c.write(delta / 'precision/results.json', json.dumps([{'ref': 's2:takeaway', 'verdict': 'supported', 'evidence': 'b'}]))
        quiet(fe.merge, Args(notes=self.root / 'notes.json', dir=delta, out=self.root / 'fidelity-eval.json', update=self.root / 'fidelity-eval.json',
                             writer_model='grok-4.7-high', reviewer_model='gpt-6.1-sol', author_model=None, answerer_model=None))
        self.assertEqual(self.score()[1]['status'], 'passed')

    def test_same_family_review_is_only_self_checked(self):
        self.save()
        packets = self.root / 'packets'
        quiet(fe.prepare, Args(notes=self.root / 'notes.json', index=self.index, out=packets, per_section=2, seed=0, questions=20, only_stale=None))
        self.answer_packets(packets)
        report = self.merge(packets, reviewer_model='cursor-grok-4.6-high')
        self.assertEqual(report['precision']['reviewer'], 'same_agent')
        self.assertEqual(self.score()[1]['status'], 'self_checked')

    def test_legacy_eval_still_binds_whole_file(self):
        self.save()
        legacy = {'schema_version': 1, 'notes_sha256': 'x', 'precision': {'items': [{'ref': 'map'}]}, 'recall': {}}
        c.write(self.root / 'fidelity-eval.json', json.dumps(legacy))
        with self.assertRaisesRegex(ValueError, 'different notes'):
            self.score()

    def test_illustration_labels_are_what_reviewers_check(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0]['visual'] = {'path': 'frame.png', 'alt': '均分', 'refs': ['p0'], 'labels': ['平均数', '总量 ÷ 样本数']}
        self.assertIn('总量 ÷ 样本数', fe.unit_text(notes, 's1:visual', self.root))
        out = subprocess.run([sys.executable, '-B', str(HERE / 'illustrate.py'), 'prompt', '--notes', str(self.save(notes)), '--ref', 's1', '--plain'],
                             capture_output=True, text=True)
        self.assertIn('- 总量 ÷ 样本数', out.stdout)
        del notes['sections'][0]['visual']['labels']
        out = subprocess.run([sys.executable, '-B', str(HERE / 'illustrate.py'), 'prompt', '--notes', str(self.save(notes)), '--ref', 's1'],
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('labels', out.stderr)


if __name__ == '__main__':
    unittest.main()
