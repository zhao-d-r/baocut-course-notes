import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HAS_CHROME = any(Path(x).exists() or shutil.which(x) for x in
                 ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', 'google-chrome', 'chromium'])


@unittest.skipUnless(HAS_CHROME, 'needs Chrome')
class RenderTest(unittest.TestCase):
    def run_render(self, mode, name, text, labels):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        (d / name).write_text(text, encoding='utf-8')
        (d / 'labels.json').write_text(json.dumps(labels, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run([sys.executable, '-B', str(HERE / 'render.py'), mode, '--dsl' if mode == 'antv' else '--html',
                            str(d / name), '--labels-json', str(d / 'labels.json'), '--out', str(d / 'out.png')],
                           capture_output=True, text=True, timeout=300)
        return r, (d / 'out.png').exists()

    def test_antv_template_words_outside_labels_fail(self):
        dsl = ('infographic compare-binary-horizontal-simple-fold\ndata\n  title 甲乙\n  compares\n'
               '    - label 甲\n      children\n        - label 快\n    - label 乙\n      children\n        - label 慢\n')
        r, png = self.run_render('antv', 's.infographic', dsl, ['甲乙', '甲', '乙', '快', '慢'])
        self.assertEqual(r.returncode, 1)
        self.assertIn('PROS', r.stdout)
        self.assertTrue(png)

    def test_freeform_page_passes_and_catches_a_line_through_text(self):
        page = ('<html><head></head><body><div id="a" style="font-size:60px;margin:100px">平均数</div>'
                '<script>window.paint=k=>{k.box("#a");%s}</script></body></html>')
        ok, png = self.run_render('page', 'p.html', page % '', ['平均数'])
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue(png)
        bad, _ = self.run_render('page', 'p.html', page % 'const r=k.rect("#a");k.line(0,r.y+r.h/2,1024,r.y+r.h/2);', ['平均数'])
        self.assertEqual(bad.returncode, 1)
        self.assertIn('crosses text', bad.stdout)


if __name__ == '__main__':
    unittest.main()
