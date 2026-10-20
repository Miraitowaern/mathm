import base64, os, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app, studio, writing

def upload(name,role,text):return {'name':name,'role':role,'content':base64.b64encode(text.encode()).decode()}

class SolvingFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name);app.init()
    def tearDown(self):app.DATA=self.old;self.tmp.cleanup()
    def test_solving_stages_route_to_references(self):
        if not (app.SKILLS/'math-modeling-skill/SKILL.md').exists():self.skipTest('缺少 math-modeling-skill')
        with patch.dict(os.environ,{'PINKPIG_API_KEY':'k','PINKPIG_MODEL':'m'},clear=True):
            t=app.create_task(dict(name='通用数模任务',flow='solving',engine='ai',consent=True,files=[upload('problem.md','problem','题目：求最优调度方案。')]))
            self.assertEqual(len(app.FLOWS['solving']),5)
            self.assertEqual([s.get('focus') for s in t['steps'] if s.get('skill')],['references/parsing.md','references/modeling.md','references/coding.md','references/visualization.md','references/review.md'])
            with patch.object(app,'model_call',return_value='## 结论\n依据：材料第1段。') as model:app.run_task(t['id'])
            self.assertEqual(model.call_count,5)
            self.assertEqual(model.call_args_list[0].kwargs['focus'],'references/parsing.md')
        result=app.get_task(t['id'])
        self.assertEqual(result['status'],'completed',result['message'])
        names=[a['name'] for a in result['artifacts']]
        self.assertIn('math-modeling-skill-parsing.md',names);self.assertIn('report.md',names)
        self.assertEqual(len(names),6)
    def test_solving_requires_problem_role(self):
        with patch.dict(os.environ,{'PINKPIG_API_KEY':'k','PINKPIG_MODEL':'m'},clear=True):
            with self.assertRaises(ValueError):app.create_task(dict(name='缺赛题',flow='solving',engine='ai',consent=True,files=[upload('notes.md','support','材料')]))

class WritingFormatTest(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.project=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_reference_normalization_and_caption_check(self):
        body='\\section{方法}\n见\\cite{ b , a ,b }。\n\\begin{figure}\\label{fig:a}\\end{figure}'
        new,report=writing.normalize_references(body,self.project)
        self.assertIn('\\cite{a,b}',new)
        self.assertIn('缺少 \\caption',report)
        self.assertNotIn('\\cite{ b , a ,b }',new)
    def test_structure_numbering_and_gap_list(self):
        outline=writing.organize_structure('\\section{方法}\n\\subsection{数据}\n\\subsection{模型}',{'paper_kind':'modeling'})
        self.assertIn('1 方法',outline);self.assertIn('1.1 数据',outline);self.assertIn('1.2 模型',outline)
        self.assertIn('尚未出现',outline)
    def test_extract_body_tolerates_fences_and_markers(self):
        self.assertEqual(writing.extract_body('% PINKPIG_BODY_START\n\\section{方法}\n正文\n% PINKPIG_BODY_END'),'\\section{方法}\n正文')
        self.assertEqual(writing.extract_body('```latex\n\\section{结果}\n正文\n```'),'\\section{结果}\n正文')
        self.assertEqual(writing.extract_body('\\section{引言}'),'\\section{引言}')
        self.assertEqual(writing.extract_body('```\n% MATHM_BODY_START\n\\section{引言}\n% MATHM_BODY_END\n```'),'\\section{引言}')
        with self.assertRaises(ValueError):writing.validate_body('% MATHM_BODY_START x % MATHM_BODY_END',Path('.'))
    def test_xlsx_text_extraction(self):
        import io, zipfile
        NS='xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr('xl/workbook.xml',f'<workbook {NS}><sheets><sheet name="结果表" sheetId="1"/></sheets></workbook>')
            z.writestr('xl/sharedStrings.xml',f'<sst {NS}><si><t>方法</t></si><si><t>数值</t></si></sst>')
            z.writestr('xl/worksheets/sheet1.xml',f'<worksheet {NS}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2"><v>1.5</v></c><c r="B2"><v>2</v></c></row></sheetData></worksheet>')
        p=Path(self.tmp.name)/'a.xlsx'; p.write_bytes(buf.getvalue())
        text,notes=app.xlsx_text(p)
        self.assertIn('方法 | 数值',text);self.assertIn('1.5 | 2',text);self.assertIn('结果表',text)
        self.assertIn('未计算',notes[0])
    def test_format_checklist_flags_unverified_without_rules(self):
        empty=writing.format_checklist('',{'paper_kind':'modeling','language':'zh'})
        self.assertIn('未上传本届规范',empty)
        filled=writing.format_checklist('全文不超过8000字，参考文献按规范著录，字号小四',{'paper_kind':'modeling','language':'zh'})
        self.assertIn('篇幅与页数',filled);self.assertIn('参考文献',filled)
    def test_audit_figures_tables_orphan_and_caption(self):
        orphan=writing.audit_figures_tables('\\begin{figure}\\caption{短}\\label{fig:a}\\end{figure}',Path('.'),{'paper_kind':'modeling'})
        self.assertIn('孤儿图表',orphan);self.assertIn('题注',orphan)
        linked=writing.audit_figures_tables('见\\ref{fig:a}。\n\\begin{figure}\\caption{'+('说'*120)+'}\\label{fig:a}\\end{figure}',Path('.'),{'paper_kind':'modeling'})
        self.assertIn('## 通过',linked)
    def test_audit_flags_missing_caption_and_duplicate_label(self):
        report=writing.audit_figures_tables('\\begin{table}\\label{tab:x}\\end{table}\n\\begin{table}\\label{tab:x}\\end{table}',Path('.'),{})
        self.assertIn('缺少 \\caption',report);self.assertIn('重复',report)

class WritingOptionsTest(unittest.TestCase):
    def test_format_actions_validated(self):
        o=studio.options({'writing_options':{'mode':'section','section':'method','format':['structure','compile','compile']}})
        self.assertEqual(o['format'],['structure','compile'])
        with self.assertRaises(ValueError):studio.options({'writing_options':{'mode':'section','format':['evil']}})
        self.assertEqual(studio.options({'writing_options':{'mode':'figure','format':['compile']}})['format'],[])
    def test_figures_and_template_style_options(self):
        o=studio.options({'writing_options':{'mode':'full','format':['figures','normalize'],'template_style':'cumcm'}})
        self.assertIn('figures',o['format']);self.assertEqual(o['template_style'],'cumcm')
        self.assertEqual(studio.options({'writing_options':{'mode':'full'}})['template_style'],'auto')
        with self.assertRaises(ValueError):studio.options({'writing_options':{'mode':'full','template_style':'bad'}})


class WritingTemplateTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name);app.init()
    def tearDown(self):app.DATA=self.old;self.tmp.cleanup()
    def _task(self,opts):
        with patch.dict(os.environ,{'PINKPIG_API_KEY':'k','PINKPIG_MODEL':'m'},clear=True):
            return app.create_task(dict(name='数模中文写作',flow='writing',engine='ai',consent=True,
                files=[upload('draft.tex','paper','\\section{方法} 有真实结果。')],writing_options=opts))
    def test_cumcm_shell_when_modeling_zh(self):
        if not (app.SKILLS/'math-modeling-skill/templates/cumcmthesis/cumcmthesis.cls').exists():self.skipTest('缺少 cumcmthesis.cls')
        t=self._task({'mode':'section','section':'method','paper_kind':'modeling','language':'zh'})
        with patch.object(app,'model_call',return_value='\\section{方法} 内容'):app.run_task(t['id'])
        r=app.get_task(t['id']);self.assertEqual(r['status'],'completed',r['message'])
        with zipfile.ZipFile(app.DATA/t['id']/'paper.zip') as z:
            self.assertIn('cumcmthesis.cls',z.namelist());self.assertIn('cumcmthesis',z.read('main.tex').decode())
        self.assertIn('国赛 cumcmthesis',r['report'])
    def test_generic_style_falls_back(self):
        t=self._task({'mode':'section','section':'method','paper_kind':'modeling','language':'zh','template_style':'generic'})
        with patch.object(app,'model_call',return_value='\\section{方法} 内容'):app.run_task(t['id'])
        r=app.get_task(t['id']);self.assertEqual(r['status'],'completed',r['message'])
        with zipfile.ZipFile(app.DATA/t['id']/'paper.zip') as z:self.assertNotIn('cumcmthesis.cls',z.namelist())

if __name__=='__main__':unittest.main()
