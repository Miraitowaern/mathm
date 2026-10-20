import base64, importlib.util, json, os, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
spec=importlib.util.spec_from_file_location('mathm',Path(__file__).parents[1]/'app.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)

def payload(name='draft.md',role='paper',content='摘要\n模型假设\n参考文献\n实际结果待验证。',**extra):
    return dict(name='测试任务',flow='review',engine='local',files=[dict(name=name,role=role,content=base64.b64encode(content.encode()).decode())],**extra)
class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name);app.init()
    def tearDown(self):app.DATA=self.old;self.tmp.cleanup()
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

class ModelConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=(app.DATA,app.ENV_FILE)
        app.DATA=Path(self.tmp.name);app.ENV_FILE=Path(self.tmp.name)/'.env';app.init()
    def tearDown(self):
        app.DATA,app.ENV_FILE=self.old;self.tmp.cleanup()
    def test_env_write_preserves_and_masks(self):
        app.ENV_FILE.write_text('# keep\nMATHM_PORT=8765\nMATHM_SKILLS_DIR=/tmp\n')
        with patch.dict(os.environ,{},clear=True):
            app.write_env_config('https://api.deepseek.com/v1','deepseek-chat','sk-abcdefghijklmnop')
            values=app.read_env_file()
            self.assertEqual(values['PINKPIG_PORT'],'8765');self.assertEqual(values['PINKPIG_SKILLS_DIR'],'/tmp')
            self.assertEqual(values['PINKPIG_MODEL'],'deepseek-chat');self.assertIn('keep',app.ENV_FILE.read_text())
            self.assertNotIn('MATHM_',app.ENV_FILE.read_text())
            cfg=app.env_config()
            self.assertTrue(cfg['has_key']);self.assertEqual(cfg['key_masked'],'sk-…mnop');self.assertNotIn('abcdefghijklmnop',cfg['key_masked'])
            self.assertEqual(app.ENV_FILE.stat().st_mode & 0o777,0o600)
    def test_env_aliases_new_over_legacy(self):
        with patch.dict(os.environ,{'MATHM_MODEL':'legacy','PINKPIG_MODEL':'next'},clear=True):
            self.assertEqual(app.env('MODEL'),'next')
        with patch.dict(os.environ,{'MATHM_MODEL':'legacy'},clear=True):
            self.assertEqual(app.env('MODEL'),'legacy')
    def test_db_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=app.DATA;app.DATA=Path(tmp)
            try:
                legacy=app.DATA/'mathm.sqlite3'
                with sqlite3.connect(legacy) as c:
                    c.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                    c.execute('INSERT INTO tasks VALUES (?,?)',('a'*32,json.dumps({'id':'a'*32,'status':'completed','created_at':'2026-01-01','steps':[],'files':[]})))
                app.init()
                self.assertTrue((app.DATA/'pinkpig.sqlite3').exists())
                self.assertEqual(app.list_tasks()[0]['id'],'a'*32)
                app.init()
                self.assertEqual([t['id'] for t in app.list_tasks()],['a'*32])
            finally:app.DATA=old
    def test_endpoint_validation(self):
        self.assertEqual(app.validate_endpoint('https://api.openai.com/v1/'),'https://api.openai.com/v1')
        self.assertEqual(app.validate_endpoint('http://127.0.0.1:11434/v1'),'http://127.0.0.1:11434/v1')
        for bad in ('ftp://x','http://example.com/v1',''):
            with self.assertRaises(ValueError):app.validate_endpoint(bad)
    def test_apply_config_hot_reload(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertFalse(app.capabilities()['ai_ready'])
            app.write_env_config('https://api.deepseek.com/v1','deepseek-chat','sk-secret-key-123456')
            app.apply_config('https://api.deepseek.com/v1','deepseek-chat','sk-secret-key-123456')
            caps=app.capabilities();self.assertTrue(caps['ai_ready']);self.assertEqual(caps['model'],'deepseek-chat')
            self.assertEqual(caps['api_key_masked'],app.mask_key('sk-secret-key-123456'))
            app.apply_config('https://api.deepseek.com/v1','',None,clear_key=True)
            self.assertFalse(app.capabilities()['ai_ready'])
    class _Response:
        def __init__(self,body):self.body=body
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self):return json.dumps(self.body).encode()
    def test_test_connection_and_models(self):
        with patch.dict(os.environ,{'MATHM_API_KEY':'k','MATHM_MODEL':'m','MATHM_BASE_URL':'https://api.example.com/v1'},clear=True):
            with patch.object(app,'urlopen',return_value=self._Response({'choices':[{'message':{'content':'pong'}}]})):
                result=app.test_connection();self.assertTrue(result['ok']);self.assertEqual(result['model'],'m')
            with patch.object(app,'urlopen',side_effect=HTTPError('https://api.example.com/v1',401,'unauthorized',{},None)):
                result=app.test_connection();self.assertFalse(result['ok']);self.assertIn('401',result['message'])
            with patch.object(app,'urlopen',return_value=self._Response({'data':[{'id':'m2'},{'id':'m1'}]})):
                self.assertEqual(app.list_models(),['m1','m2'])
        with patch.dict(os.environ,{},clear=True):
            self.assertFalse(app.test_connection()['ok'])

if __name__=='__main__':unittest.main()
