import base64, importlib.util, os, sys, tempfile, time, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,writing
SKILLROOT=app.SKILLS
TEMPLATE='\\documentclass{article}\n\\begin{document}\n封面\n% MATHM_BODY_START\n原区域\n% MATHM_BODY_END\n\\end{document}\n'
def upload(name,role,text):return {'name':name,'role':role,'content':base64.b64encode(text.encode()).decode()}
class WritingTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(app.DATA,app.SKILLS);app.DATA=Path(self.tmp.name);app.SKILLS=SKILLROOT;app.init()
 def tearDown(self):app.DATA,app.SKILLS=self.old;self.tmp.cleanup()
 def make(self):
  with patch.dict(os.environ,{'MATHM_API_KEY':'test','MATHM_MODEL':'mock'}):
   return app.create_task({'name':'模板写作测试','flow':'writing','engine':'ai','consent':True,'files':[upload('main.tex','template',TEMPLATE),upload('results.md','paper','方法：实测均值；结果：样本10个，均值3。')]})
 def test_template_and_cleanup(self):
  t=self.make()
  with patch.object(app,'model_call',return_value='\\section{结果}\n样本10个，均值3。'):
   app.run_task(t['id'])
  result=app.get_task(t['id']);self.assertEqual(result['status'],'completed',result['message'])
  folder=app.DATA/t['id'];self.assertFalse((folder/'scratch').exists())
  with zipfile.ZipFile(folder/'paper.zip') as z:
   source=z.read('main.tex').decode();pre,_,post=writing.template_parts(TEMPLATE)
   self.assertTrue(source.startswith(pre));self.assertTrue(source.endswith(post));self.assertEqual(set(z.namelist()),{'main.tex','checks.md'})
  self.assertEqual(len(result['artifacts']),2)
 def test_invalid_output_and_cleanup(self):
  t=self.make()
  with patch.object(app,'model_call',return_value='\\geometry{margin=1cm}'):
   app.run_task(t['id'])
  self.assertEqual(app.get_task(t['id'])['status'],'failed');self.assertFalse((app.DATA/t['id']/'scratch').exists());self.assertFalse((app.DATA/t['id']/'paper.zip').exists())
 def test_template_requires_markers(self):
  with self.assertRaises(ValueError):writing.template_parts('\\begin{document}x\\end{document}')
 def test_unknown_citation_or_image(self):
  for code in ['\\cite{invented}','\\includegraphics{missing.png}','\\section{unclosed','\\begin{table}x\\end{figure}']:
   with self.assertRaises(ValueError):writing.validate_body(code,app.DATA)
 def test_cleanup_scope(self):
  folder=app.DATA/('a'*32);folder.mkdir();scratch=folder/'scratch';scratch.mkdir();(scratch/'draft.tex').write_text('temp');(folder/'original.tex').write_text('keep');(folder/'paper.zip').write_text('keep')
  os.utime(scratch,(time.time()-90000,)*2);writing.cleanup(app.DATA)
  self.assertFalse(scratch.exists());self.assertTrue((folder/'original.tex').exists());self.assertTrue((folder/'paper.zip').exists())
if __name__=='__main__':unittest.main()
