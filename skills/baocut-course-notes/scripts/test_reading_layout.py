import base64
import contextlib
import copy
import hashlib
import html
import re
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as Args
import unittest
import course_notes as c
import reading_layout as layout


class EditorialTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.note = {'title': '另一门课 <script>', 'limitations': ['只复用冻结资料'], 'read_chunks': ['c1'],
                     'summary': ['信息完整保留'], 'self_test': [{'question': '为什么？', 'answer': '因为约束', 'section': 1}],
                     'supplements': [{'title': '材料解释', 'text': '补充独有细节 <script>', 'source_label': '讲义未口述', 'source_url': 'https://example.org', 'pages': [9]}],
                     'sections': [{'title': '定义', 'start': 0, 'end': 5, 'source_ids': ['a'], 'paragraphs': ['关键定义'], 'examples': ['实际例子'], 'editor_notes': ['适用边界'], 'frames': []},
                                  {'title': '结尾', 'start': 6, 'end': 10, 'source_ids': ['b'], 'paragraphs': ['结尾原话'], 'frames': [{'source_type': 'pdf_page', 'path': 'page.png', 'source_label': '冻结讲义', 'page': 9, 'caption': '配套图'}]}]}
        self.data = {'version': 1, 'course_title': '测试课程', 'issue': 'X', 'title': '自由标题', 'subtitle': '不写死第五课', 'sections': [
            {'short': '定义', 'takeaway': '明确约束', 'terms': ['关键定义'], 'flow': 'p0 e0 n0 x0 f2:0'},
            {'short': '结尾', 'takeaway': '保留原话', 'terms': ['结尾'], 'flow': 'p0'}]}
        (self.root / 'page.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
        c.write(self.root / 'index.json', json.dumps({'chunks': [{'id': 'c1'}], 'sentences': [{'id': 'a', 'start': 0, 'end': 5}, {'id': 'b', 'start': 6, 'end': 10}]}))

    def bind(self):
        raw = json.dumps(self.note, ensure_ascii=False).encode()
        self.data['notes_sha256'] = hashlib.sha256(raw).hexdigest()
        return raw

    def validate(self):
        return layout.validate(self.note, self.data, self.bind())

    def render(self):
        (self.root / 'notes.json').write_bytes(self.bind())
        c.write(self.root / 'reading-layout.json', json.dumps(self.data))
        with contextlib.redirect_stdout(io.StringIO()):
            c.render(Args(notes=self.root/'notes.json', index=self.root/'index.json', out=self.root/'out.html', require_layout=True))
        return (self.root/'out.html').read_text()

    def test_end_to_end_preserves_and_integrates(self):
        page = self.render()
        first = page.split('<section id="s1">')[1].split('</section>')[0]
        self.assertLess(first.index('补充独有细节 &lt;script&gt;'), first.index('data-frame="2:0"'))
        self.assertEqual(page.count('data-frame="2:0"'), 1)
        for text in ['关键定义', '实际例子', '适用边界', '结尾原话', '因为约束', 'PDF物理页 9']:
            self.assertIn(text, html.unescape(re.sub(r"<[^>]+>", "", page)))
        self.assertIn('<strong>关键定义</strong>', page)
        self.assertNotIn('id="supplements"', page)
        self.assertIn('2 节 · 1 幅配图 · 1 道自测', page)
        self.assertNotIn('<script>', first)
        self.assertIn('<details class="quiz-answer">', page)

    def test_issue_badge_only_shows_short_numbers(self):
        from reading_layout import issue_badge
        self.assertEqual([issue_badge(x) for x in ('7', '第 8 讲', '第5讲', 'L10', '09')], ['07', '08', '05', '10', '09'])
        for long in ('Breakout Session · Turing Room · 2026-10-14', '2026', '10/14', '第 2 讲 / 2026-09-28', '', None):
            self.assertEqual(issue_badge(long), '')

    def test_omission_fails_instead_of_silent_loss(self):
        self.data['sections'][0]['flow'] = 'p0 e0 x0 f2:0'
        with self.assertRaisesRegex(ValueError, 'omits'): self.validate()

    def test_alias_duplicate_is_detected(self):
        self.data['sections'][1]['flow'] += ' f0'
        with self.assertRaisesRegex(ValueError, 'Duplicate'): self.validate()

    def test_unmapped_supplement_fails(self):
        self.data['sections'][0]['flow'] = 'p0 e0 n0 f2:0'
        with self.assertRaisesRegex(ValueError, 'omits'): self.validate()

    def test_stale_binding_fails(self):
        raw = self.bind()
        with self.assertRaisesRegex(ValueError, 'Stale'): layout.validate(self.note, self.data, raw+b' ')

    def test_video_cannot_move_outside_its_section(self):
        self.note['sections'][1]['frames'][0].update(source_type='video_frame', time=8)
        with self.assertRaisesRegex(ValueError, 'Video frame'): self.validate()

    def test_invalid_or_negative_reference_fails(self):
        for token in ['p-1', 'f0:0', 'f9:0', 'x8', 'p2:0']:
            with self.subTest(token=token):
                self.data['sections'][0]['flow'] = 'p0 e0 n0 x0 '+token
                with self.assertRaises(ValueError): self.validate()

    def test_emphasis_cannot_silently_do_nothing(self):
        self.data['sections'][0]['terms'] = ['并不存在的结论']
        with self.assertRaisesRegex(ValueError, 'not found'): self.validate()

    def test_no_optional_features_or_images_required(self):
        self.note.pop('summary'); self.note.pop('self_test'); self.note.pop('supplements')
        self.note['sections'][1]['frames'] = []
        self.data['sections'][0]['flow'] = 'p0 e0 n0'
        page = self.render()
        self.assertNotIn('href="#summary"', page)
        self.assertNotIn('id="self-test"', page)
        self.assertIn('0 幅配图', page)

    def test_summary_emphasis_is_bound_to_summary(self):
        self.data['summary_terms'] = ['正文有但摘要没有']
        with self.assertRaisesRegex(ValueError, 'Summary emphasis term not found'):
            self.validate()

    def test_legacy_alias_works(self):
        self.note['official_slide_supplements'] = self.note.pop('supplements')
        self.assertIn('补充独有细节 &lt;script&gt;', self.render())

    def test_require_layout_does_not_fallback(self):
        (self.root/'notes.json').write_bytes(self.bind())
        with self.assertRaisesRegex(ValueError, 'requires reading-layout'):
            c.render(Args(notes=self.root/'notes.json', index=self.root/'index.json', out=self.root/'out.html', require_layout=True))


if __name__ == '__main__':
    unittest.main()
