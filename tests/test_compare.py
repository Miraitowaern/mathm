import base64, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app, compare

def upload(name,role,text):return {'name':name,'role':role,'content':base64.b64encode(text.encode()).decode()}


class CompareMetricsTest(unittest.TestCase):
    def test_metrics_helper(self):
        m=compare.metrics('图1 图2 表1 [1] [2] '+('中'*10))
        self.assertEqual(m['figures'],2);self.assertEqual(m['tables'],1);self.assertEqual(m['references'],2)
        self.assertIn('摘要',compare.metrics('摘要 关键词')['sections'])


class CompareFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name);app.init()
    def tearDown(self):app.DATA=self.old;self.tmp.cleanup()
    def test_requires_baseline(self):
        with self.assertRaises(ValueError):
            app.create_task(dict(name='对比',flow='compare',engine='local',files=[upload('a.md','paper','摘要 正文')]))
    def test_requires_paper(self):
        with self.assertRaises(ValueError):
            app.create_task(dict(name='对比',flow='compare',engine='local',files=[upload('b.md','support','摘要 正文')]))
    def test_reports_deterministic_gaps(self):
        subject='摘要 关键词 参考文献 [1] 图1 表1 '+('正'*300)
        baseline='摘要 关键词 参考文献 附录 模型假设 [1] [2] 图1 图2 表1 '+('基'*600)
        t=app.create_task(dict(name='对比',flow='compare',engine='local',
            files=[upload('mine.md','paper',subject),upload('best.md','support',baseline)]))
        app.run_task(t['id'])
        r=app.get_task(t['id'])
        self.assertEqual(r['status'],'completed',r['message'])
        self.assertIn('仅反映结构层面',r['report'])
        self.assertIn('差距清单',r['report'])
        names=[a['name'] for a in r['artifacts']]
        self.assertIn('comparison.md',names);self.assertIn('comparison.zip',names)
        self.assertFalse((app.DATA/t['id']/'scratch').exists())


if __name__=='__main__':unittest.main()
