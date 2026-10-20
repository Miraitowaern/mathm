import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import outline


class OutlineTest(unittest.TestCase):
    def test_normalize_assigns_sid_and_links(self):
        items = outline.normalize_items([{'title': '方法', 'anchor': 'method'}, {'title': ''}, {'title': '结果', 'anchor': 'results'}], 'modeling')
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['next'], items[1]['sid'])
        self.assertEqual(items[1]['prev'], items[0]['sid'])
        self.assertEqual(items[0]['prev'], None)

    def test_section_numbers_levels(self):
        items = outline.normalize_items([{'title': 'A', 'level': 1}, {'title': 'B', 'level': 2}, {'title': 'C', 'level': 2}, {'title': 'D', 'level': 1}])
        nums = outline.section_numbers(items)
        self.assertEqual([nums[i['sid']] for i in items], ['1', '1.1', '1.2', '2'])

    def test_writing_order_puts_method_results_first(self):
        items = outline.normalize_items([{'title': '摘要', 'anchor': 'abstract'}, {'title': '方法', 'anchor': 'method'}, {'title': '引言', 'anchor': 'intro'}])
        order = outline.writing_order(items)
        self.assertEqual(order[0], items[1]['sid'])

    def test_figure_numbering_by_citing_section(self):
        items = outline.normalize_items([{'title': 'A'}, {'title': 'B'}])
        figs = [{'fid': 'f2', 'kind': 'generated', 'citing_sections': [items[1]['sid']]},
                {'fid': 'f1', 'kind': 'generated', 'citing_sections': [items[0]['sid']]},
                {'fid': 't1', 'kind': 'table', 'citing_sections': [items[0]['sid']]}]
        num = outline.figure_numbering(figs, items)
        self.assertEqual(num['figures'], {'f1': 1, 'f2': 2})
        self.assertEqual(num['tables'], {'t1': 1})

    def test_crossref_audit(self):
        body = '见\\ref{fig:a} 与 \\ref{fig:missing}。\n\\begin{figure}\\label{fig:a}\\end{figure}\n\\begin{table}\\label{tab:orphan}\\end{table}'
        items = outline.crossref_audit(body)
        messages = ' '.join(i['message'] for i in items)
        self.assertIn('tab:orphan', messages)
        self.assertIn('fig:missing', messages)

    def test_paragraph_index_stable_pid(self):
        body = '第一段内容。\n\n第二段内容。'
        a = outline.paragraph_index(body)
        b = outline.paragraph_index(body.replace('\n\n', '\n\n\n'))
        self.assertEqual([p['pid'] for p in a], [p['pid'] for p in b])
        self.assertEqual(len(a), 2)
        self.assertIsNotNone(outline.find_paragraph(body, a[0]['pid']))

    def test_mainline_gaps(self):
        gaps = outline.mainline_gaps({'question': 'q', 'method': 'm', 'results': [{'claim': 'c', 'evidence': []}]})
        joined = ' '.join(gaps)
        self.assertIn('bounds', joined)
        self.assertIn('术语', joined)


if __name__ == '__main__':
    unittest.main()
