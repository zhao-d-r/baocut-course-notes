import base64
import contextlib
import copy
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as Args
import unittest
import course_notes as c

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text x="1" y="5">图</text></svg>'


def v3_notes():
    return {
        'schema_version': 3, 'title': '测试课', 'limitations': ['测试样本'], 'read_chunks': ['chunk-0001', 'chunk-0002'],
        'map': {'path': 'visuals/map.svg', 'alt': '课程地图'}, 'summary': ['平均数是总量除以样本数。'], 'summary_terms': ['平均数'],
        'groups': [{'start': 1, 'label': '一 / 理解'}],
        'sections': [
            {'title': '均分', 'short': '均分', 'takeaway': '平均数是均分后的量。', 'start': 0, 'end': 50, 'source_ids': ['a'],
             'terms': ['平均数'], 'flow': 'p0 f0 n0 x0',
             'visual': {'path': 'visuals/s1.svg', 'alt': '三个盒子均分', 'refs': ['p0', 'f0']},
             'paragraphs': ['平均数等于总量除以样本数 <b>'], 'editor_notes': [{'text': '整理者说明。', 'caveat': '只用整数'}],
             'frames': [{'source_type': 'video_frame', 'path': 'frame.png', 'time': 10, 'caption': '方块图'}]},
            {'title': '核对范围', 'short': '核对', 'takeaway': '先核对样本。', 'start': 310, 'end': 360, 'source_ids': ['b'],
             'paragraphs': ['比较前核对单位。'], 'frames': []},
        ],
        'supplements': [{'title': '补充', 'text': '外部说明平均数。', 'source_label': '外部资料', 'source_url': 'https://example.org'},
                        {'title': '未放置', 'text': '独立延伸。', 'source_label': '外部资料'}],
        'bridges': {'x0': '衔接说明。'},
        'self_test': [{'question': '平均数？', 'answer': '总量除以样本数。', 'section': 1}],
    }


class LayeredTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        rows = [{'id': 'a', 'start': 0, 'end': 20, 'text': '均分'}, {'id': 'b', 'start': 310, 'end': 330, 'text': '范围'}]
        c.write(self.root / 'export.json', json.dumps({'sentences': rows}))
        with contextlib.redirect_stdout(io.StringIO()):
            c.chunks(Args(input=self.root / 'export.json', out=self.root / 'chunks'))
        (self.root / 'frame.png').write_bytes(PNG)
        (self.root / 'visuals').mkdir()
        (self.root / 'visuals/map.svg').write_text(SVG, encoding='utf-8')
        (self.root / 'visuals/s1.svg').write_text(SVG, encoding='utf-8')
        self.notes = v3_notes()

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, notes=None, **extra):
        c.write(self.root / 'notes.json', json.dumps(notes or self.notes, ensure_ascii=False))
        with contextlib.redirect_stdout(io.StringIO()):
            c.render(Args(notes=self.root / 'notes.json', index=self.root / 'chunks/index.json', out=self.root / 'out.html', **extra))
        return (self.root / 'out.html').read_text(encoding='utf-8')

    def test_layers_render_and_keep_every_unit(self):
        page = self.render()
        self.assertIn('class="mode-bar"', page)
        self.assertEqual(page.count('data:image/svg+xml;base64,'), 2)
        self.assertIn('details class="deep"', page)
        self.assertIn('等于总量除以样本数 &lt;b&gt;', page)
        self.assertIn('<b>核对与边界</b>只用整数', page)
        self.assertIn('<a class="ref" href="#s1-p0"><span class="item-no">1</span>课堂段落</a>', page)
        self.assertIn('id="s1-p0"', page)
        self.assertIn('整理者衔接：衔接说明。', page)
        self.assertIn('延伸资料', page)  # unplaced supplement is still shown
        self.assertIn('独立延伸。', page)

    def test_flow_defaults_to_section_order(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0].pop('flow')
        notes['sections'][0]['terms'] = []
        page = self.render(notes)
        self.assertLess(page.index('data-content="s1:p0"'), page.index('data-content="s1:n0"'))

    def test_omitted_unit_fails(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0]['flow'] = 'p0 f0'
        with self.assertRaisesRegex(ValueError, 'omits content'):
            self.render(notes)

    def test_visual_refs_must_point_into_flow(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0]['visual']['refs'] = ['p3']
        with self.assertRaisesRegex(ValueError, 'refs'):
            self.render(notes)

    def test_visual_must_be_svg_inside_run(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0]['visual']['path'] = 'frame.gif'
        with self.assertRaisesRegex(ValueError, 'svg'):
            self.render(notes)
        notes['sections'][0]['visual']['path'] = '../outside.svg'
        with self.assertRaisesRegex(ValueError, 'svg|inside'):
            self.render(notes)

    def test_generated_illustration_needs_declared_labels(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0]['visual']['path'] = 'frame.png'
        with self.assertRaisesRegex(ValueError, 'labels'):
            self.render(notes)
        notes['sections'][0]['visual']['labels'] = ['平均数', '均分']
        self.assertIn('data:image/png;base64', self.render(notes))
        (self.root / 'fake.png').write_text('not an image', encoding='utf-8')
        notes['sections'][0]['visual']['path'] = 'fake.png'
        with self.assertRaisesRegex(ValueError, 'PNG/JPEG/WebP'):
            self.render(notes)

    def test_takeaway_required_and_layout_flag_rejected(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][1]['takeaway'] = ' '
        with self.assertRaisesRegex(ValueError, 'takeaway'):
            self.render(notes)
        with self.assertRaisesRegex(ValueError, 'layout'):
            self.render(layout=self.root / 'reading-layout.json')

    def test_coverage_still_enforced_for_v3(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][1]['source_ids'] = []
        with self.assertRaisesRegex(ValueError, 'evidence'):
            self.render(notes)

    def test_bad_caveat_object_rejected(self):
        notes = copy.deepcopy(self.notes)
        notes['sections'][0]['paragraphs'][0] = {'text': '正文', 'source': 'lecturer'}
        with self.assertRaisesRegex(ValueError, 'caveat'):
            self.render(notes)


if __name__ == '__main__':
    unittest.main()
