import base64, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app, project, outline

NS = lambda: SimpleNamespace(**vars(app))


def up(name, role, text, purpose='用途'):
    return {'name': name, 'role': role, 'content': base64.b64encode(text.encode()).decode(), 'purpose': purpose}


class ProjectCrudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = app.DATA; app.DATA = Path(self.tmp.name); app.init()
        self.ns = NS()
    def tearDown(self):
        app.DATA = self.old; self.tmp.cleanup()

    def test_create_requires_name_and_valid_kind(self):
        with self.assertRaises(ValueError): project.create_project(self.ns, {'name': ''})
        with self.assertRaises(ValueError): project.create_project(self.ns, {'name': 'x', 'paper_kind': 'bad'})
        p = project.create_project(self.ns, {'name': '论文', 'paper_kind': 'modeling', 'stage': 'scoping'})
        self.assertEqual(p['stage'], 'scoping')
        self.assertEqual(len(project.list_projects(self.ns)), 1)

    def test_material_requires_purpose(self):
        p = project.create_project(self.ns, {'name': '论文'})
        with self.assertRaises(ValueError): project.add_files(self.ns, p['id'], 'material', [{'name': 'a.md', 'content': base64.b64encode(b'x').decode()}])
        p = project.add_files(self.ns, p['id'], 'material', [up('a.md', 'problem', '题目内容', '赛题说明')])
        self.assertEqual(p['files'][0]['role'], 'problem')
        self.assertEqual(p['stage'], 'material')
        self.assertTrue((project.project_dir(self.ns, p['id']) / (p['files'][0]['id'] + '.md')).exists())

    def test_rejects_reserved_and_bad_suffix(self):
        p = project.create_project(self.ns, {'name': '论文'})
        with self.assertRaises(ValueError): project.add_files(self.ns, p['id'], 'material', [up('main.tex', 'paper', 'x', 'p')])
        with self.assertRaises(ValueError): project.add_files(self.ns, p['id'], 'material', [up('bad.exe', 'support', 'x', 'p')])

    def test_template_markers_and_main(self):
        p = project.create_project(self.ns, {'name': '论文', 'paper_kind': 'modeling', 'language': 'zh'})
        tex = '\\documentclass{article}\n\\setCJKmainfont{SomeFont}\n\\begin{document}\n% PINKPIG_BODY_START\n% PINKPIG_BODY_END\n\\end{document}\n'
        p = project.add_files(self.ns, p['id'], 'template', [up('t.tex', 'template', tex, '')])
        t = p['template']
        self.assertEqual(t['main'], 't.tex')
        self.assertEqual(t['writable_region']['kind'], 'markers')
        self.assertTrue(t['writable_region']['confident'])
        self.assertIn('SomeFont', t['fonts']['declared'])
        self.assertEqual(t['engine_hint'], 'xelatex')

    def test_template_without_markers_flags_document_env(self):
        p = project.create_project(self.ns, {'name': '论文'})
        tex = '\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n'
        p = project.add_files(self.ns, p['id'], 'template', [up('t2.tex', 'template', tex, '')])
        self.assertEqual(p['template']['writable_region']['kind'], 'document-env')
        self.assertFalse(p['template']['writable_region']['confident'])
        self.assertTrue(any(i['severity'] == 'must' for i in p['template']['issues']))

    def test_rules_checklist_and_conflict(self):
        p = project.create_project(self.ns, {'name': '论文'})
        tex = '\\documentclass{ctexart}\n\\setCJKmainfont{Songti SC}\n\\begin{document}\n% PINKPIG_BODY_START\n% PINKPIG_BODY_END\n\\end{document}'
        pid = p['id']
        p = project.add_files(self.ns, pid, 'template', [up('t.tex', 'template', tex, '')])
        p = project.add_files(self.ns, pid, 'rules', [up('rules.txt', 'rules', '摘要不超过300字，正文字体宋体', '')])
        project.post_route(self.ns, project.get_project(self.ns, pid), '/rules', {'extra': '参考文献按规范著录'})
        r = project.get_project(self.ns, pid)['rules']
        self.assertTrue(any(i['group'] == '摘要与关键词' for i in r['items']))
        self.assertTrue(any(i['source'] == 'extra' for i in r['items']))
        self.assertTrue(r['conflicts'])

    def test_references_registry_missing_and_duplicates(self):
        p = project.create_project(self.ns, {'name': '论文'})
        bib = '@article{a,title={A}} @article{a,title={A2}} @book{b,title={B}}'
        p = project.add_files(self.ns, p['id'], 'reference', [up('refs.bib', 'reference', bib, '')])
        body = '% PINKPIG_BODY_START\n见\\cite{a,c}。\n% PINKPIG_BODY_END\n'
        p = project.add_files(self.ns, p['id'], 'material', [up('draft.tex', 'paper', body, '初稿')])
        # registry rebuilt on body change
        p2 = project.get_project(self.ns, p['id'])
        p2['references'] = project.references_registry(self.ns, p2); project.save_project(self.ns, p2)
        refs = p2['references']
        self.assertIn('a', refs['stats']['duplicates'])
        self.assertEqual([m['key'] for m in refs['missing']], ['c'])


class ProjectJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = app.DATA; app.DATA = Path(self.tmp.name); app.init()
    def tearDown(self):
        app.DATA = self.old; self.tmp.cleanup()

    def _project(self, **kw):
        ns = NS()
        p = project.create_project(ns, {'name': '论文', 'paper_kind': 'modeling', 'language': 'zh', **kw})
        p = project.add_files(ns, p['id'], 'material', [up('d.md', 'paper', '真实方法与结果，图1 表1。', '初稿')])
        return ns, p

    def _job(self, ns, p, kind):
        job = {'id': 'j' * 32, 'kind': kind, 'target': None, 'status': 'queued', 'progress': 0, 'message': '',
               'steps': [{'name': n, 'status': 'pending'} for n in project.JOB_STEPS[kind]],
               'events': [], 'cancel_requested': False, 'notes': []}
        p['active_job'] = job; project.save_project(ns, p)
        return job['id']

    def test_mainline_json_roundtrip(self):
        ns, p = self._project(); jid = self._job(ns, p, 'mainline')
        payload = json.dumps({'question': '调度问题', 'method': 'MILP', 'assumptions': ['线性'],
                              'terms': [{'term': 'T', 'definition': '周期', 'unit': 's'}],
                              'results': [{'claim': '提升10%', 'evidence': [], 'source': 'real'}], 'bounds': '静态场景',
                              'missing_evidence': []})
        with patch.object(app, 'model_call', return_value=payload) as m:
            nss = NS()
            project.run_job(nss, p['id'], jid, 'mainline', None, {})
        self.assertTrue(m.called)
        got = project.get_project(ns, p['id'])
        self.assertEqual(got['mainline']['question'], '调度问题')
        self.assertEqual(got['active_job']['status'], 'completed')
        self.assertIn('结果“提升10%”缺少证据引用。', got['mainline']['missing_evidence'])

    def test_outline_assigns_local_sid(self):
        ns, p = self._project(); jid = self._job(ns, p, 'outline')
        payload = json.dumps({'items': [{'sid': 'model-made', 'title': '方法', 'anchor': 'method', 'question': 'q'}],
                              'reading_order': [], 'writing_order': []})
        with patch.object(app, 'model_call', return_value=payload):
            project.run_job(NS(), p['id'], jid, 'outline', None, {})
        got = project.get_project(ns, p['id'])
        items = got['outline']['items']
        self.assertEqual(len(items), 1)
        self.assertNotEqual(items[0]['sid'], 'model-made')
        self.assertEqual(items[0]['next'], None)

    def test_section_draft_then_adopt_and_restore(self):
        ns, p = self._project()
        _, body = project.post_route(ns, p, '/outline', {'action': 'save', 'items': [{'title': '方法', 'anchor': 'method', 'question': 'q'}]})
        sid = body['outline']['items'][0]['sid']
        jid = self._job(ns, p, 'section')
        with patch.object(app, 'model_call', return_value='```latex\n\\section{方法} 内容 $a=b$\n```'):
            project.run_job(NS(), p['id'], jid, 'section', sid, {'sid': sid})
        got = project.get_project(ns, p['id'])
        self.assertEqual(got['sections'][sid]['status'], 'draft')
        project.post_route(ns, got, '/sections/%s' % sid, {'action': 'adopt'})
        got = project.get_project(ns, p['id'])
        self.assertEqual(got['sections'][sid]['status'], 'adopted')

    def test_section_rejects_dangerous_latex(self):
        ns, p = self._project()
        _, body = project.post_route(ns, p, '/outline', {'action': 'save', 'items': [{'title': '方法', 'anchor': 'method'}]})
        sid = body['outline']['items'][0]['sid']; jid = self._job(ns, p, 'section')
        with patch.object(app, 'model_call', return_value='\\usepackage{geometry}\n\\section{x}'):
            project.run_job(NS(), p['id'], jid, 'section', sid, {'sid': sid})
        got = project.get_project(ns, p['id'])
        self.assertEqual(got['active_job']['status'], 'failed')
        self.assertNotIn(sid, got['sections'])

    def test_polish_accept_and_locfail(self):
        ns, p = self._project()
        _, body = project.post_route(ns, p, '/outline', {'action': 'save', 'items': [{'title': '方法', 'anchor': 'method'}]})
        sid = body['outline']['items'][0]['sid']
        sec = project.get_project(ns, p['id'])
        sec['sections'][sid] = {'sid': sid, 'title': '方法', 'body_latex': '这句话需要润色。另外一句。', 'status': 'adopted', 'versions': []}
        project.save_project(ns, sec)
        jid = self._job(ns, sec, 'polish')
        payload = json.dumps({'items': [{'original': '这句话需要润色。', 'suggestion': '本句已润色。', 'reason': '清晰'},
                                        {'original': '不存在的句子', 'suggestion': 'x', 'reason': 'y'}],
                              'related': [{'sid': sid, 'proposed_change': '建议下次修改', 'reason': 'r'}]})
        with patch.object(app, 'model_call', return_value=payload):
            project.run_job(NS(), p['id'], jid, 'polish', None, {'target': {'scope': 'section', 'sid': sid}, 'kind': 'language'})
        got = project.get_project(ns, p['id'])
        rid = got['revisions'][-1]['rid']
        project.post_route(ns, got, '/revisions/%s/decide' % rid, {'action': 'accept', 'iid': 'all'})
        got = project.get_project(ns, p['id'])
        self.assertIn('本句已润色。', got['sections'][sid]['body_latex'])
        self.assertTrue(got['sections'][sid]['versions'])
        statuses = [i['status'] for i in got['revisions'][-1]['items']]
        self.assertIn('accepted', statuses); self.assertIn('rejected', statuses)

    def test_check_deterministic_without_model(self):
        ns, p = self._project()
        _, body = project.post_route(ns, p, '/outline', {'action': 'save', 'items': [{'title': '方法', 'anchor': 'method'}]})
        sid = body['outline']['items'][0]['sid']
        got = project.get_project(ns, p['id'])
        got['sections'][sid] = {'sid': sid, 'title': '方法', 'body_latex': '这里待补充。', 'status': 'adopted', 'versions': []}
        project.save_project(ns, got)
        jid = self._job(ns, got, 'check')
        project.run_job(ns, p['id'], jid, 'check', None, {'use_ai': False})
        got = project.get_project(ns, p['id'])
        self.assertFalse(got['check_report']['model_used'])
        self.assertTrue(got['check_report']['summary']['must'] >= 1)

    def test_build_export_packages(self):
        ns, p = self._project()
        tex = '\\documentclass[UTF8,a4paper,12pt]{ctexart}\n\\usepackage{amsmath}\n\\begin{document}\n% PINKPIG_BODY_START\n% PINKPIG_BODY_END\n\\end{document}\n'
        project.add_files(ns, p['id'], 'template', [up('t.tex', 'template', tex, '')])
        _, body = project.post_route(ns, project.get_project(ns, p['id']), '/outline', {'action': 'save', 'items': [{'title': '方法', 'anchor': 'method'}]})
        sid = body['outline']['items'][0]['sid']
        got = project.get_project(ns, p['id'])
        got['sections'][sid] = {'sid': sid, 'title': '方法', 'body_latex': '正文内容。', 'status': 'adopted', 'versions': []}
        project.save_project(ns, got)
        jid = self._job(ns, got, 'build')
        project.run_job(ns, p['id'], jid, 'build', None, {})
        got = project.get_project(ns, p['id'])
        names = [a['name'] for a in got['build']['artifacts']]
        self.assertIn('latex-project.zip', names); self.assertIn('build-report.md', names)
        self.assertTrue((project.build_dir(ns, got) / 'latex-project.zip').exists())
        self.assertFalse((project.project_dir(ns, got['id']) / 'scratch').exists())

    def test_generated_figure(self):
        ns, p = self._project()
        csv = {'name': 'data.csv', 'role': 'support', 'content': base64.b64encode(b'x,y\n1,2\n2,4\n3,6\n').decode(), 'purpose': '结果'}
        p = project.add_files(ns, p['id'], 'material', [csv])
        src = next(f for f in p['files'] if f['suffix'] == '.csv')
        p = project.insert_figure(ns, p, {'kind': 'generated', 'source_file_id': src['id'], 'chart_type': 'line',
                                          'x_column': 'x', 'y_columns': 'y', 'x_label': 'X', 'y_label': 'Y', 'caption': '示例图'})
        fig = p['figures'][0]
        self.assertEqual(fig['number'], 1)
        self.assertTrue((project.project_dir(ns, p['id']) / 'figures' / fig['fid'] / 'figure.png').exists())


if __name__ == '__main__':
    unittest.main()
