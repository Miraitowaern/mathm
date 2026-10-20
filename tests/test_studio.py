import base64,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,studio,assets

def file(name,text,role='support'):
 return {'name':name,'role':role,'content':base64.b64encode(text.encode()).decode()}
class StudioTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name);app.init()
 def tearDown(self):app.DATA=self.old;self.tmp.cleanup()
 def make(self,mode,files,**opts):
  with patch.dict(os.environ,{'MATHM_API_KEY':'test','MATHM_MODEL':'mock'}):
   return app.create_task(dict(name='科研模块验收',flow='writing',engine='local' if mode in ('figure','table') else 'ai',consent=True,files=files,writing_options={'mode':mode,'paper_kind':'research',**opts}))
 def test_section_no_template_nature_and_language(self):
  t=self.make('section',[file('evidence.md','已有证据：方法A在十个测试样本上平均误差0.3。')],section='results',language='en')
  with patch.object(app,'model_call',return_value='\\section{Results}\nThe mean error was 0.3.') as model:app.run_task(t['id'])
  result=app.get_task(t['id']);self.assertEqual(result['status'],'completed',result['message'])
  self.assertEqual(model.call_args.kwargs['writing_options']['section'],'results')
  with zipfile.ZipFile(app.DATA/t['id']/'paper.zip') as z:self.assertIn('section.tex',z.namelist());self.assertIn(b'\\documentclass',z.read('main.tex'))
 def test_prompt_routes_and_overrides_defaults(self):
  o=studio.options({'writing_options':{'mode':'section','paper_kind':'research','section':'discussion','language':'zh'}})
  prompt,loaded=studio.guidance(app.SKILLS,o)
  self.assertTrue(any('discussion-argument-language' in n for n in loaded));self.assertIn('只写选定章节',prompt);self.assertIn('中文任务不因',prompt)
  o['action']='polish';prompt,loaded=studio.guidance(app.SKILLS,o);self.assertTrue(any(n.startswith('nature-polishing/') for n in loaded))
 def test_modeling_and_research_options_stored(self):
  t=self.make('section',[file('draft.tex','\\section{方法}已有实验。','paper')],paper_kind='modeling',section='assumptions')
  self.assertEqual(t['writing_options']['paper_kind'],'modeling')
 def test_table_local_exact_and_escaped(self):
  t=self.make('table',[file('results.csv','method,value\nA&B,0.300\nC_1,2.00\n')],caption='Result 100%')
  with patch.object(app,'model_call',side_effect=AssertionError('must not call model')):app.run_task(t['id'])
  result=app.get_task(t['id']);self.assertEqual(result['status'],'completed',result['message'])
  with zipfile.ZipFile(app.DATA/t['id']/'table.zip') as z:
   tex=z.read('table.tex').decode();self.assertIn('A\\&B',tex);self.assertIn('C\\_1',tex);self.assertIn('0.300',tex);self.assertIn('100\\%',tex)
  self.assertFalse((app.DATA/t['id']/'scratch').exists())
 def test_real_figure_pipeline(self):
  t=self.make('figure',[file('results.csv','epoch,baseline,proposed\n1,0.1,0.2\n2,0.3,0.4\n3,0.4,0.6\n')],x_column='epoch',y_columns='baseline,proposed',x_label='Epoch',y_label='Score')
  app.run_task(t['id']);result=app.get_task(t['id']);self.assertEqual(result['status'],'completed',result['message'])
  with zipfile.ZipFile(app.DATA/t['id']/'figure.zip') as z:
   for n in ['figure.pdf','figure.svg','figure.png','plot.py','source-data.csv','figure.tex']:self.assertIn(n,z.namelist())
  self.assertFalse((app.DATA/t['id']/'scratch').exists())
 def test_invalid_csv_fails_without_silent_dropping(self):
  for content in ['x,y\n1,NaN\n','x,y\n1,\n','x,y\n1,2,3\n']:
   t=self.make('figure',[file('results.csv',content)],x_column='x',y_columns='y')
   app.run_task(t['id']);self.assertEqual(app.get_task(t['id'])['status'],'failed');self.assertFalse((app.DATA/t['id']/'scratch').exists())
 def test_config_validation(self):
  for raw in [{'mode':'execute'},{'section':'evil'},{'language':'xx'}]:
   with self.assertRaises(ValueError):studio.options({'writing_options':raw})
 def test_no_ai_needed_for_table(self):
  with patch.dict(os.environ,{},clear=True):
   t=app.create_task(dict(name='本地表格',flow='writing',engine='local',writing_options={'mode':'table'},files=[file('results.csv','a,b\n1,2')]))
  app.run_task(t['id']);self.assertEqual(app.get_task(t['id'])['status'],'completed')
if __name__=='__main__':unittest.main()
