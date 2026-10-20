import sys, tempfile, types, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import solve


class SolverPreflightTest(unittest.TestCase):
    def test_rejects_banned_imports(self):
        ready,findings=solve.validate_solver_source('import os\nprint(1)')
        self.assertFalse(ready);self.assertTrue(any(f['check']=='BANNED-IMPORT' for f in findings))
    def test_rejects_eval_and_dunder(self):
        self.assertFalse(solve.validate_solver_source('eval("1")')[0])
        self.assertFalse(solve.validate_solver_source('x=().__class__')[0])
    def test_accepts_safe_script(self):
        ready,findings=solve.validate_solver_source('import math\nimport numpy as np\nprint(math.pi)')
        self.assertTrue(ready,findings)
    def test_reports_syntax_error(self):
        ready,findings=solve.validate_solver_source('def f(:\n')
        self.assertFalse(ready);self.assertEqual(findings[0]['check'],'SYNTAX')
    def test_read_numeric_table_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'a.csv';p.write_text('x,y\n1,2\n3,5\n',encoding='utf-8')
            headers,rows=solve.read_numeric_table(p)
            self.assertEqual(headers,['x','y']);self.assertEqual(rows[0],['1','2'])


class LocalNumericTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_descriptive_and_correlation(self):
        tid='a'*32;fid='b'*32;folder=self.data/tid;folder.mkdir()
        (folder/(fid+'.csv')).write_text('x,y\n1,2\n2,4\n3,6\n4,8\n',encoding='utf-8')
        app=types.SimpleNamespace(DATA=self.data)
        t={'id':tid,'files':[{'id':fid,'suffix':'.csv','name':'d.csv','role':'support'}],'artifacts':[]}
        md,notes=solve.local_numeric(app,t,[])
        self.assertIn('均值',md);self.assertIn('Pearson',md);self.assertIn('1.0000',md)
        self.assertTrue((folder/'local-results.md').exists());self.assertTrue((folder/'descriptive.csv').exists())
        self.assertIn({'name':'descriptive.csv','url':f'/api/tasks/{tid}/artifacts/descriptive.csv'},t['artifacts'])
    def test_no_data_is_honest(self):
        app=types.SimpleNamespace(DATA=self.data)
        t={'id':'c'*32,'files':[{'id':'d'*32,'suffix':'.md','name':'p.md','role':'problem'}],'artifacts':[]}
        md,notes=solve.local_numeric(app,t,[])
        self.assertEqual(md,'');self.assertIn('未执行数值计算',notes[0])


class SandboxRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def _app(self,script):
        return types.SimpleNamespace(DATA=self.data,MODELING_SKILL='m',
            model_call=lambda *a,**k:'```python\n'+script+'```')
    def test_runs_safe_script_and_collects_solution(self):
        tid='e'*32;folder=self.data/tid;folder.mkdir()
        script='import json\njson.dump({"answer": 42}, open("solution.json","w"))\nprint("done")\n'
        t={'id':tid,'files':[],'artifacts':[],'topic':'','year':'2025'}
        md,notes=solve.sandbox_run(self._app(script),t,[])
        self.assertIn('"answer": 42',md)
        self.assertTrue((folder/'solver.py').exists());self.assertTrue((folder/'solution-summary.md').exists())
        self.assertFalse((folder/'scratch').exists())
    def test_rejects_unsafe_script_without_running(self):
        tid='f'*32;folder=self.data/tid;folder.mkdir()
        t={'id':tid,'files':[],'artifacts':[],'topic':'','year':'2025'}
        with self.assertRaises(ValueError):solve.sandbox_run(self._app('import os\n'),t,[])
        self.assertFalse((folder/'scratch').exists())


if __name__=='__main__':unittest.main()
