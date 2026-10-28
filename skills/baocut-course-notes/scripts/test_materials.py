import unittest
import materials as m


class LinksTest(unittest.TestCase):
    def test_links_in_html_and_script_bundles(self):
        page = '<p>Week 4</p><a href="/syllabus">Syllabus</a><a href="https://docs.google.com/document/d/abc_1/edit">Calendar</a>'
        rows = m.scan(page, 'https://course.example/', 'page', True)
        self.assertEqual([(r['url'], r['text']) for r in rows],
                         [('https://course.example/syllabus', 'Syllabus'), ('https://docs.google.com/document/d/abc_1/edit', 'Calendar')])
        # A JS-rendered schedule keeps the slides link only in its bundle; the surrounding text names the lecture.
        js = '{title:"Guest: Lee Robinson",links:[{label:"Slides",href:"https://drive.google.com/file/d/1b8W_x/view?usp=drive_link"}]}'
        row = m.scan(js, 'https://course.example/a.js', 'script', False)[0]
        self.assertEqual(row['url'], 'https://drive.google.com/file/d/1b8W_x/view?usp=drive_link')
        self.assertIn('Lee Robinson', row['context'])

    def test_kinds_and_exports(self):
        self.assertEqual(m.kind('https://docs.google.com/presentation/d/x/edit'), 'slides')
        self.assertEqual(m.kind('https://drive.google.com/file/d/x/view'), 'pdf_or_drive_file')
        self.assertEqual(m.kind('https://arxiv.org/abs/2401.1'), 'paper')
        self.assertEqual(m.doc_export('https://docs.google.com/document/d/abc_1/edit'), 'https://docs.google.com/document/d/abc_1/export?format=html')
        self.assertIsNone(m.doc_export('https://example.org/x.pdf'))
        self.assertEqual(m.page_list('3,5-7', 10), [3, 5, 6, 7])
        with self.assertRaisesRegex(ValueError, 'outside'):
            m.page_list('9-11', 10)


if __name__ == '__main__':
    unittest.main()
