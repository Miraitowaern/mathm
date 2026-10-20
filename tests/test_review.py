import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review


def _project(body):
    return {'paper_kind': 'modeling', 'sections': {'s1': {'sid': 's1', 'body_latex': body, 'status': 'adopted'}},
            'outline': {'items': [{'sid': 's1', 'title': '方法'}]}, 'references': None, 'rules': None}


class ReviewTest(unittest.TestCase):
    def test_full_body_joins_sections(self):
        self.assertEqual(review.full_body(_project('abc')), 'abc')

    def test_deterministic_flags_placeholder(self):
        items = review.deterministic_checks(_project('这里待补充内容。'))
        self.assertTrue(any(i['category'] == '待补充' and i['severity'] == 'must' for i in items))

    def test_deterministic_runs_without_model(self):
        items = review.deterministic_checks(_project('没有占位。'))
        self.assertTrue(all(i['source'] == 'deterministic' for i in items))

    def test_scope_filter_sections(self):
        items = review.deterministic_checks(_project('待补充'), {'kind': 'sections', 'sids': []})
        # project-wide items without a sid are kept; none should carry a sid outside the scope
        self.assertTrue(all(not i['location'].get('sid') for i in items))

    def test_merge_dedupes_and_summarizes(self):
        det = [{'id': '1', 'category': 'x', 'severity': 'must', 'source': 'deterministic', 'location': {'quote': 'abc'}, 'message': 'same'}] 
        ai = [{'category': 'x', 'severity': 'must', 'source': 'ai', 'location': {'quote': 'abc'}, 'message': 'same'}]
        merged = review.merge(ai, det)
        self.assertEqual(len(merged), 1)
        s = review.summary([{'severity': 'must', 'source': 'ai'}])
        self.assertEqual(s['must'], 1); self.assertEqual(s['ai'], 1)

    def test_render_groups_by_severity(self):
        report = {'run_at': 't', 'model_used': False, 'truncated': False,
                  'items': [{'category': 'c', 'severity': 'must', 'source': 'deterministic', 'location': {}, 'message': 'm', 'suggestion': 's'}],
                  'summary': review.summary([{'severity': 'must', 'source': 'deterministic'}])}
        md = review.render(report)
        self.assertIn('必须处理', md); self.assertIn('未调用模型', md)


if __name__ == '__main__':
    unittest.main()
