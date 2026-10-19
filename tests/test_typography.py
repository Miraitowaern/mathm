import sys,unittest,tempfile,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio,typography,assets
class TypographyTest(unittest.TestCase):
 def test_safe_font_settings(self):
  o=studio.options({'writing_options':{'font_latin':'Times New Roman','font_cjk':'Songti SC','font_size':'10.5','instructions':'控制在500字'}})
  self.assertEqual(o['instructions'],'控制在500字')
  with self.assertRaises(ValueError):typography.settings({'font_latin':'bad}\\input{secret'})
  with self.assertRaises(ValueError):typography.settings({'instructions':'x'*4001})
 def test_writing_font_group_preserves_template(self):
  o={'font_latin':'Times New Roman','font_cjk':'Songti SC','font_size':'10.5'}
  body=typography.latex_wrap('实际结果',o,r'\documentclass{ctexart}')
  self.assertIn(r'\fontspec{Times New Roman}',body);self.assertIn(r'\CJKfontspec{Songti SC}',body);self.assertIn(r'\fontsize{10.5}{13.65}',body)
  with self.assertRaises(ValueError):typography.latex_wrap('body',o,r'\documentclass{article}')
 def test_table_fonts_and_prompt_effect(self):
  o={'mode':'table','instructions':'表头加粗\n数值列右对齐','font_latin':'Times New Roman','font_cjk':'inherit','font_size':'10'}
  tex=assets.table(['Method','Score'],[['A','0.300'],['B','0.400']],'Results',o)
  self.assertIn(r'\begin{tabular}{lr}',tex);self.assertIn(r'\textbf{Method}',tex);self.assertIn(r'\fontspec{Times New Roman}',tex)
  self.assertLess(tex.index(r'\begin{table}'),tex.index(r'\fontsize'));self.assertIn('0.300',tex)
 def test_figure_prompts_and_fonts(self):
  o=studio.options({'writing_options':{'mode':'figure','instructions':'去掉网格；图例放在底部；显示数据点；标题：对比','font_size':'9','font_latin':'Arial','x_column':'x','y_columns':'y'}})
  s=assets.chart_settings(['x','y'],[['1','2']],o)
  self.assertFalse(s['grid']);self.assertEqual(s['legend'],'bottom');self.assertTrue(s['markers']);self.assertEqual(s['font_size'],'9');self.assertEqual(s['title'],'对比')
 def test_unknown_local_prompt_not_ignored(self):
  with self.assertRaises(ValueError):studio.options({'writing_options':{'mode':'table','instructions':'编造更好的实验数值'}})
 def test_prompt_forwarded_into_writing_rules(self):
  import app
  o=studio.options({'writing_options':{'instructions':'重点解释泛化边界','paper_kind':'research','mode':'section'}})
  text,_=studio.guidance(app.SKILLS,o);self.assertIn('重点解释泛化边界',text)
if __name__=='__main__':unittest.main()
