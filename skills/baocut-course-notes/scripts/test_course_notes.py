import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as Args
import unittest
import course_notes as c


class HandoffTest(unittest.TestCase):
    def test_roundtrip_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            rows = [{'id':'a', 'start':0, 'end':10, 'text':'定义与例子'}, {'id':'b', 'start':310, 'end':320, 'text':'下一节'}]
            c.write(root/'export.json', json.dumps({'sentences':rows}))
            c.chunks(Args(input=root/'export.json', out=root/'chunks'))
            index = c.read_json(root/'chunks/index.json')
            self.assertEqual(len(index['chunks']), 2)
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
            (root/'frame.png').write_bytes(png)
            n = {'title':'测试<script>', 'source_url':'https://example.com', 'limitations':['测试样本'], 'read_chunks':['chunk-0001','chunk-0002'], 'sections':[{'title':'一', 'start':0, 'end':320, 'source_ids':['a','b'], 'paragraphs':['完整正文 <script>'], 'frames':[{'path':'frame.png','time':5,'caption':'图'}]}]}
            def render():
                c.write(root/'notes.json', json.dumps(n))
                c.render(Args(notes=root/'notes.json', index=root/'chunks/index.json', out=root/'note.html'))
            render()
            page=(root/'note.html').read_text()
            self.assertIn('data:image/png;base64,', page)
            self.assertIn('测试&lt;script&gt;', page)
            n['read_chunks'].pop()
            with self.assertRaisesRegex(ValueError, 'ledger'): render()
            n['read_chunks'].append('chunk-0002')
            n['sections'][0]['source_ids']=['a']
            with self.assertRaisesRegex(ValueError, 'coverage'): render()
            n['sections'][0]['source_ids']=['a','b']
            n['sections'][0]['frames'][0]['time']=400
            with self.assertRaisesRegex(ValueError, 'outside'): render()
            n['sections'][0]['frames'][0]['time']=5
            n['sections'][0]['frames'][0]['path']='missing.png'
            with self.assertRaises(OSError): render()

    def test_baocut3_segments_export(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            segs = [{'id':'run-1', 'start':1.4, 'end':20.7, 'text':'So as mentioned, I am Lee.', 'speaker':'说话人 1', 'words':[]}]
            c.write(root/'export.json', json.dumps({'schema':'baocut.transcript', 'segments':segs}))
            c.chunks(Args(input=root/'export.json', out=root/'chunks'))
            self.assertEqual(c.read_json(root/'chunks/index.json')['sentences'][0]['id'], 'run-1')

    def test_project_protection(self):
        with self.assertRaisesRegex(ValueError, '.bcut'):
            c.safe_path('/tmp/example.bcut/transcript.json')




class EvidenceV2Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.note = {'title':'测试', 'limitations':['仅转写阅读'], 'read_chunks':['chunk-0001'], 'omitted':[], 'sections':[{'title':'主题', 'start':0, 'end':10, 'source_ids':['a'], 'paragraphs':['课堂原意'], 'frames':[]}]}
        c.write(self.root/'index.json', json.dumps({'chunks':[{'id':'chunk-0001'}], 'sentences':[{'id':'a','start':0,'end':10}]}))
        (self.root/'frame.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))

    def render(self):
        c.write(self.root/'notes.json', json.dumps(self.note))
        with contextlib.redirect_stdout(io.StringIO()):
            c.render(Args(notes=self.root/'notes.json',index=self.root/'index.json',out=self.root/'out.html'))
        return (self.root/'out.html').read_text()

    def test_optional_content_preserved_and_escaped(self):
        self.note.update(summary=['摘要不应丢失<script>'],self_test=[{'question':'为何？','answer':'有条件的答案','section':1}],supplements=[{'title':'未讲主题','text':'补充正文<script>','source_label':'官方讲义','pages':[2,3],'source_url':'https://example.org/slides.pdf'}])
        page=self.render()
        for content in ['摘要不应丢失&lt;script&gt;','有条件的答案','补充正文&lt;script&gt;','href="#s1"','PDF物理页 2、3']:
            self.assertIn(content,page)
        self.assertNotIn('补充正文<script>',page)

    def pdf_frame(self):
        return {'source_type':'pdf_page','path':'frame.png','page':3,'source_label':'官方讲义','caption':'结果图'}

    def test_pdf_has_no_fabricated_capture_time(self):
        f=self.pdf_frame();self.note['sections'][0]['frames']=[f]
        page=self.render();caption=page.split('<figcaption>')[1].split('</figcaption>')[0]
        self.assertIn('PDF物理页 3',caption);self.assertNotIn('00:',caption);self.assertNotIn('视频原帧',caption)
        f['related_time']=5
        page=self.render();self.assertIn('相关讲解 00:00:05（不是同秒视频截图）',page)

    def test_pdf_capture_time_rejected(self):
        f=self.pdf_frame();f['time']=5;self.note['sections'][0]['frames']=[f]
        with self.assertRaisesRegex(ValueError,'capture time'):self.render()

    def test_invalid_pdf_page_and_navigation_rejected(self):
        f=self.pdf_frame();self.note['sections'][0]['frames']=[f]
        for value in [0,True,1.5]:
            f['page']=value
            with self.assertRaisesRegex(ValueError,'physical page'):self.render()
        f['page']=3;f['related_time']=11
        with self.assertRaisesRegex(ValueError,'outside'):self.render()

    def test_duplicate_evidence_rejected(self):
        self.note['sections'].append(dict(self.note['sections'][0]))
        with self.assertRaisesRegex(ValueError,'Duplicate evidence'):self.render()

    def test_duplicate_omission_rejected(self):
        self.note['omitted']=[{'id':'a','reason':'休息'},{'id':'a','reason':'休息'}]
        with self.assertRaisesRegex(ValueError,'omission'):self.render()

    def test_bad_self_test_reference_rejected(self):
        self.note['self_test']=[{'question':'问题','answer':'答案','section':2}]
        with self.assertRaisesRegex(ValueError,'existing section'):self.render()

    def test_executable_source_url_rejected(self):
        self.note['supplements']=[{'title':'补充','text':'正文','source_label':'来源','source_url':'javascript:alert(1)'}]
        with self.assertRaisesRegex(ValueError,'http'):self.render()

    def test_legacy_supplement_preserved(self):
        self.note['official_slide_supplements']=[{'title':'旧补充','text':'旧内容仍应出现','pages':[2]}]
        self.assertIn('旧内容仍应出现',self.render())
        self.note['supplements']=[{'title':'新','text':'新','source_label':'新'}]
        with self.assertRaisesRegex(ValueError,'not both'):self.render()

if __name__=='__main__': unittest.main()
