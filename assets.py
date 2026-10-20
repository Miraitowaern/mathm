"""Deterministic, local figure/table generation; no uploaded/generated code execution."""
import csv, io, json, math, os, shutil, subprocess, sys, zipfile
import typography
from pathlib import Path

def read_csv(path):
    raw=path.read_bytes()
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise ValueError('CSV 请保存为 UTF-8 编码')
    rows=list(csv.reader(io.StringIO(text),strict=True))
    if len(rows)<2:raise ValueError('CSV 需要表头和至少一行数据')
    if len(rows)>10001 or len(rows[0])>20:raise ValueError('CSV 最多10000行数据、20列，不会自动截断')
    headers=rows[0]
    if any(not x.strip() for x in headers) or len(set(headers))!=len(headers):raise ValueError('CSV 表头不能为空或重复')
    if any(len(r)!=len(headers) for r in rows[1:]):raise ValueError('CSV 各行列数不一致，请检查分隔符或缺失单元格')
    return headers,rows[1:]

def escape_tex(value):
    mapping={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
    return ''.join(mapping.get(ch,ch) for ch in str(value)).replace('\n',' ').replace('\r',' ')

def table(headers,rows,caption,o=None):
    if len(rows)>200:raise ValueError('单张表最多200行；请明确拆表，不能自动删减数据')
    o=o or {};directives=typography.commands(dict(o,mode='table'));caption=directives.get('caption',caption)
    align=['c' if directives.get('alignment')=='center' else 'l']*len(headers)
    if directives.get('numeric_right'):
        for i in range(len(headers)):
            try:
                if all(math.isfinite(float(row[i])) for row in rows):align[i]='r'
            except ValueError:pass
    heading=[escape_tex(h) for h in headers]
    if directives.get('bold_header'):heading=[r'\textbf{'+h+'}' for h in heading]
    lines=[r'\begin{table}[htbp]',r'\centering',r'\caption{'+escape_tex(caption or 'Results')+'}',r'\label{tab:results}',r'\begin{tabular}{'+''.join(align)+'}',r'\toprule',' & '.join(heading)+r' \\',r'\midrule']
    lines += [' & '.join(map(escape_tex,row))+r' \\' for row in rows]
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    content=typography.latex_wrap('\n'.join(lines[2:-1])+'\n',o)
    return '\n'.join(lines[:2])+'\n'+content+'\n'+lines[-1]+'\n'

def chart_settings(headers,rows,o):
    x=o['x_column']
    ys=[v.strip() for v in o['y_columns'].split(',') if v.strip()]
    if x not in headers or not ys or any(y not in headers for y in ys):raise ValueError('请填写 CSV 的实际 X 列名和 Y 列名，多个 Y 列用英文逗号分隔')
    if x in ys or len(set(ys))!=len(ys) or len(ys)>8:raise ValueError('X 与 Y 列不能重复，Y 列最多8个')
    if o['chart_type']=='bar' and len(rows)>40:raise ValueError('柱状图最多40行，请明确提供所需比较数据，应用不会自动抽样')
    for row in rows:
        for name in ys+([] if o['chart_type']=='bar' else [x]):
            try:v=float(row[headers.index(name)])
            except ValueError:raise ValueError('列 '+name+' 存在非数值或缺失值，未自动删除数据')
            if not math.isfinite(v):raise ValueError('数据含 NaN 或无穷值，未自动删除数据')
    return typography.commands(o)|{k:o[k] for k in ('chart_type','x_label','y_label','font_latin','font_cjk','font_size')}|{'x_column':x,'y_columns':ys}|typography.commands(o)

def run(app,t,o):
    folder=app.DATA/t['id'];scratch=folder/'scratch';project=scratch/'project'
    t.update(status='running',progress=0,report=None,artifacts=[],preview=None)
    for step in t['steps']:step['status']='pending'
    app.save(t)
    try:
        if scratch.exists():shutil.rmtree(scratch)
        project.mkdir(parents=True)
        app.checkpoint(t,0);app.event(t,'本地读取 CSV；不调用模型、不上传数据')
        f=next(f for f in t['files'] if f['suffix']=='.csv');original=folder/(f['id']+'.csv')
        headers,rows=read_csv(original);f.update(characters=0,notes=[f'{len(rows)}行数据，{len(headers)}列；数据不裁剪、不聚合、不推断物理含义'])
        shutil.copy2(original,project/'source-data.csv')
        app.checkpoint(t,0,'done');app.checkpoint(t,1)
        if o['mode']=='figure':settings=chart_settings(headers,rows,o)
        app.checkpoint(t,1,'done');app.checkpoint(t,2)
        summary=[f'- 字体设置：西文 {o.get("font_latin","inherit")}；中文 {o.get("font_cjk","inherit")}；字号 {o.get("font_size","inherit")}（inherit=模板或默认字体）。', '- 本任务的提示词与设置已保存；本地指令已按支持列表解析。',f'- 数据：{len(rows)}行，{len(headers)}列；所有行原样使用，无自动删值、抽样或统计检验。']
        if o['mode']=='table':
            body=table(headers,rows,o['caption'],o);(project/'table.tex').write_text(body,encoding='utf-8');t['preview']=body
            summary+=['- 生成 booktabs 三线表，数值与字符串按原值输出，特殊字符已转义。','- 表格需要主文档加载 booktabs；自定义字体还需 fontspec/xeCJK 并用 XeLaTeX 编译（中文文档可用 ctex），本机字体可用性未验证；宽度、分页和引用编号请在论文中调整；未编译检查版面。']
        else:
            (project/'settings.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
            shutil.copy2(Path(__file__).with_name('figure_renderer.py'),project/'plot.py')
            env=os.environ.copy();env['MPLCONFIGDIR']=str(scratch/'mpl');env['MPLBACKEND']='Agg'
            audits={}
            source_audit=app.SKILLS/'nature-figure/scripts/validate_figure.py'
            if source_audit.exists():
                checked=subprocess.run([sys.executable,'-B',str(source_audit),str(project/'plot.py'),'--json'],capture_output=True,text=True,timeout=20)
                audits['source']=json.loads(checked.stdout)
                if checked.returncode==1:raise ValueError('图片源码检查未通过，请检查固定绘图模板')
            process=subprocess.run([sys.executable,'-B',str(project/'plot.py')],cwd=project,env=env,capture_output=True,text=True,timeout=60)
            if process.returncode:raise ValueError('本地绘图失败；请确认绘图依赖已内置，数据列及字体可用。'+process.stderr[-350:])
            summary+=['- Python 本地生成 PNG（600dpi）、PDF 和 SVG；包内含固定绘图脚本、原始 CSV 和列映射，可复现。','- 仅生成用户选择的折线、柱状或散点图；不生成虚构误差线和显著性标记。']
            # Run the bundled Nature collision auditor against the actual PDF. Never claim an audit passed when unavailable.
            audit=app.SKILLS/'nature-figure/scripts/audit_figure_collisions.py'
            if audit.exists():
                result=subprocess.run([sys.executable,'-B',str(audit),str(project/'figure.pdf'),'--json-out',str(scratch/'collision.json')],capture_output=True,text=True,timeout=30)
                status='未完成'
                if (scratch/'collision.json').exists():
                    data=json.loads((scratch/'collision.json').read_text());status=str(data.get('verdict','已运行，见记录'))
                    audits['collisions']=data
                summary+=['- Nature PDF 碰撞检查：'+status+f'（退出码{result.returncode}）。仍需作者在最终尺寸检查标签、单位和数据含义。']
                if result.returncode==1:raise ValueError('图片碰撞检查发现必须修复的问题，请缩短标签、减少同图系列或调整数据布局后重试')
            else:summary+=['- Nature PDF 碰撞审查工具不可用，未声称通过投稿级图片审查。']
            text_audit=app.SKILLS/'nature-figure/scripts/audit_pdf_text.py'
            if text_audit.exists():
                checked=subprocess.run([sys.executable,'-B',str(text_audit),str(project/'figure.pdf'),'--json'],capture_output=True,text=True,timeout=20)
                audits['pdf_text']=json.loads(checked.stdout)
                if checked.returncode==1:raise ValueError('PDF 字号检查未通过，未交付图片')
            audits['panel_alignment']='NOT APPLICABLE: single-panel figure'
            (project/'validation.json').write_text(json.dumps(audits,ensure_ascii=False,indent=2),encoding='utf-8')
            snippet='\\begin{figure}[htbp]\n\\centering\n\\includegraphics[width=0.8\\linewidth]{figure.pdf}\n\\caption{'+escape_tex(o['caption'] or 'Results')+'}\n\\label{fig:results}\n\\end{figure}\n'
            (project/'figure.tex').write_text(snippet,encoding='utf-8');t['preview']=snippet
        app.checkpoint(t,2,'done');app.checkpoint(t,3)
        # Final notes are small; diagnostics and font caches remain disposable.
        report='# '+('数据图' if o['mode']=='figure' else '论文表格')+'交付\n\n'+'\n'.join(summary)+'\n- 所有操作在本机完成；上传原件与最终成果保留，临时文件结束即清理。\n'
        (project/'checks.md').write_text(report,encoding='utf-8')
        app.checkpoint(t,3,'done');app.checkpoint(t,4)
        name='figure.zip' if o['mode']=='figure' else 'table.zip'
        with zipfile.ZipFile(scratch/name,'w',zipfile.ZIP_DEFLATED) as z:
            for file in project.iterdir():z.write(file,file.name)
        app.checkpoint(t,4,'done');app.checkpoint(t,5)
        (scratch/name).replace(folder/name);(folder/'checks.md').write_text(report,encoding='utf-8')
        artifacts=[name,'checks.md']
        if o['mode']=='figure':shutil.copy2(project/'figure.png',folder/'figure.png');artifacts.append('figure.png')
        t['artifacts']=[{'name':n,'url':f'/api/tasks/{t["id"]}/artifacts/{n}'} for n in artifacts]
        t['report']=report;app.checkpoint(t,5,'done');t['status']='completed';app.event(t,'本地生成完成；临时文件已清理')
    except Exception as e:
        t['status']='cancelled' if isinstance(e,InterruptedError) else 'failed'
        for step in t['steps']:
            if step['status']=='running':step['status']='failed'
        app.event(t,str(e)[:450] if isinstance(e,(ValueError,InterruptedError,csv.Error)) else '本地生成失败：'+type(e).__name__)
    finally:
        if scratch.exists():shutil.rmtree(scratch)
