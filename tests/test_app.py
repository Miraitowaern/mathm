from _support import fixture_skills
import base64, importlib.util, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('mathm',Path(__file__).parents[1]/'app.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)

def payload(name='draft.md',role='paper',content='摘要\n模型假设\n参考文献\n实际结果待验证。',**extra):
    return dict(name='测试任务',flow='review',engine='local',files=[dict(name=name,role=role,content=base64.b64encode(content.encode()).decode())],**extra)
class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=(app.DATA,app.SKILLS);app.DATA=Path(self.tmp.name);app.SKILLS=fixture_skills(app.DATA/"skills");app.init()
    def tearDown(self):app.DATA,app.SKILLS=self.old;self.tmp.cleanup()
    def test_real_local_pipeline(self):
        t=app.create_task(payload());app.run_task(t['id']);t=app.get_task(t['id'])
        self.assertEqual(t['status'],'completed');self.assertEqual(t['progress'],100)
        self.assertEqual(sum(s['status']=='skipped' for s in t['steps']),3)
        self.assertIn('未执行AI语义审查',t['report']);self.assertEqual(t['files'][0]['characters'],len('摘要\n模型假设\n参考文献\n实际结果待验证。'))
        self.assertTrue((app.DATA/t['id']/'report.md').exists())
    def test_path_and_role_validation(self):
        for name in ('../evil.md','bad.exe','x\\evil.md'):
            with self.assertRaises(ValueError):app.create_task(payload(name=name))
        with self.assertRaises(ValueError):app.create_task(payload(role='support'))
        with self.assertRaises(ValueError):app.create_task(payload(role='unknown'))
    def test_invalid_encoding(self):
        p=payload();p['files'][0]['content']='bad!'
        with self.assertRaises(ValueError):app.create_task(p)
    def test_ai_config_required(self):
        p=payload();p['engine']='ai'
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):app.create_task(p)
    def test_ai_stages_invoke_skills(self):
        p=payload(consent=True);p['engine']='ai'
        with patch.dict(os.environ,{'MATHM_API_KEY':'test','MATHM_MODEL':'test-model'}):
            t=app.create_task(p)
            with patch.object(app,'model_call',return_value='## 发现\n依据：文件第1段。') as model:
                app.run_task(t['id']);self.assertEqual(model.call_count,3)
        t=app.get_task(t['id']);self.assertEqual(t['status'],'completed');self.assertEqual(len(t['artifacts']),4)
    def test_cancel_survives_worker_save(self):
        t=app.create_task(payload());stale=dict(t)
        t['cancel_requested']=True;app.save(t);app.save(stale)
        self.assertTrue(app.get_task(t['id'])['cancel_requested']);app.run_task(t['id'])
        self.assertEqual(app.get_task(t['id'])['status'],'cancelled')
    def test_restart_recovery(self):
        t=app.create_task(payload());t['status']='running';app.save(t);app.init()
        self.assertEqual(app.get_task(t['id'])['status'],'interrupted')
    def test_failure_is_not_success(self):
        t=app.create_task(payload(name='broken.pdf'))
        app.run_task(t['id']);t=app.get_task(t['id']);self.assertEqual(t['status'],'failed');self.assertIsNone(t['report'])
    def test_model_failure_retains_artifact(self):
        p=payload(consent=True);p['engine']='ai'
        with patch.dict(os.environ,{'MATHM_API_KEY':'test','MATHM_MODEL':'test-model'}):
            t=app.create_task(p)
            with patch.object(app,'model_call',side_effect=['first report',ValueError('模型服务失败')]):app.run_task(t['id'])
        t=app.get_task(t['id']);self.assertEqual(t['status'],'failed');self.assertEqual(len(t['artifacts']),1)
if __name__=='__main__':unittest.main()
