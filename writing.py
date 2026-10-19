"""Template-bounded writing; no execution of uploaded TeX; private disposable scratch."""
import re, shutil, threading, time, zipfile
from pathlib import Path
START='% MATHM_BODY_START'
END='% MATHM_BODY_END'
_cleanup_roots=set()

def template_parts(text):
    if text.count(START)!=1 or text.count(END)!=1:
        raise ValueError('主模板须各包含一次 % MATHM_BODY_START 和 % MATHM_BODY_END，放在 document 内指定正文位置；可下载示例模板')
    pre,rest=text.split(START);body,post=rest.split(END)
    if r'\begin{document}' not in pre or r'\end{document}' not in post:
        raise ValueError('写作区域必须在 document 环境内，不能覆盖导言区或封面')
    return pre+START,body,END+post

def cleanup(root, current_time=None):
    """Only remove task scratch older than 24h; preserve sources, uploads, final outputs."""
    cutoff=(current_time or time.time())-86400
    for task in root.iterdir():
        if not re.fullmatch('[a-f0-9]{32}',task.name) or task.is_symlink() or not task.is_dir():continue
        tmp=task/'scratch'
        if tmp.is_symlink():continue
        try:
            if tmp.is_dir() and tmp.stat().st_mtime<cutoff:shutil.rmtree(tmp)
        except OSError:pass

def start_cleanup(root):
    root=Path(root)
    cleanup(root)
    if str(root) in _cleanup_roots:return
    _cleanup_roots.add(str(root))
    def loop():
        while True:
            time.sleep(3600)
            try:cleanup(root)
            except OSError:pass
    threading.Thread(target=loop,daemon=True,name='mathm-cleanup').start()

def validate_body(body, project):
    if not body.strip() or '```' in body or START in body or END in body:raise ValueError('模型未返回纯 LaTeX 正文，请重试')
    code=re.sub(r'(?<!\\)%[^\n]*','',body)
    if re.search(r'\\(?:documentclass|usepackage|geometry|newgeometry|pagestyle|setmainfont|setCJKmainfont|input|include|includeonly|openin|openout|read|write|immediate|special|directlua|catcode|csname|newcommand|renewcommand|def|let|pdfobj|usepackage)\b|\\(?:begin|end)\s*\{document\}',code):
        raise ValueError('模型尝试修改模板设置、读取外部文件或加入文档外壳，已拒绝交付')
    stack=[]
    for m in re.finditer(r'\\(begin|end)\s*\{([^}]+)\}',code):
        if m[1]=='begin':stack.append(m[2])
        elif not stack or stack.pop()!=m[2]:raise ValueError('LaTeX 环境不配对，需重新生成')
    if stack:raise ValueError('LaTeX 环境未闭合，输出可能被截断')
    balance=0
    for m in re.finditer(r'(?<!\\)[{}]',code):
        balance+=1 if m[0]=='{' else -1
        if balance<0:raise ValueError('LaTeX 花括号不配对')
    if balance:raise ValueError('LaTeX 花括号未闭合')
    for m in re.finditer(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}',code):
        value=m[1]
        if not any((project/(value+ext)).is_file() for ext in ('','.pdf','.png','.jpg','.jpeg','.eps')):
            raise ValueError('模型引用了未提供的图片：'+value)
    bibkeys=set()
    for p in project.glob('*.bib'):
        bibkeys.update(re.findall(r'@\w+\s*\{\s*([^,\s]+)',p.read_text(encoding='utf-8-sig')))
    bibkeys.update(re.findall(r'\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}',code))
    for keys in re.findall(r'\\cite\w*\*?(?:\[[^\]]*\])*\{([^}]+)\}',code):
        if any(k.strip() not in bibkeys for k in keys.split(',')):raise ValueError('模型使用了未提供的参考文献键：'+keys)

def run(app,t):
    import studio,typography
    o=t.get('writing_options') or studio.options({})
    if o['mode'] in ('figure','table'):
        import assets
        return assets.run(app,t,o)
    folder=app.DATA/t['id'];scratch=folder/'scratch';project=scratch/'project'
    t.update(status='running',report=None,progress=0,artifacts=[])
    for s in t['steps']:s['status']='pending'
    app.save(t)
    try:
        if scratch.exists():shutil.rmtree(scratch)
        project.mkdir(parents=True)
        app.checkpoint(t,0);app.event(t,'读取模板、规范与真实研究材料；不保存解析副本')
        material=[];template=None;main_name=None
        for f in t['files']:
            source=folder/(f['id']+f['suffix'])
            if f['role']=='template':
                template=source.read_text(encoding='utf-8-sig');main_name=f['name'];text=template;notes=[]
            elif f['suffix'] in ('.png','.jpg','.jpeg','.eps'):
                text='';notes=['作为图片资源打包；模型未查看图片内容']
            else:
                text,notes,_=app.extract(source,f['suffix'])
            f.update(characters=len(text),notes=notes)
            material.append(f'\n[文件 {f["name"]}；角色 {f["role"]}]\n{text}')
            if f['suffix'] in ('.tex','.bib','.cls','.sty','.bst','.png','.jpg','.jpeg','.eps') or (f['suffix']=='.pdf' and f['role']=='support'):
                shutil.copy2(source,project/f['name'])
        if template is None:
            cls=r'\documentclass[UTF8,a4paper,12pt]{ctexart}' if o['language']=='zh' else r'\documentclass[a4paper,12pt]{article}'
            if o.get('font_latin','inherit')!='inherit':cls+='\n'+r'\usepackage{fontspec}'
            if o['language']=='en' and o.get('font_cjk','inherit')!='inherit':cls+='\n'+r'\usepackage{xeCJK}'
            template=cls+'\n'+r'\usepackage{amsmath,amssymb,graphicx,booktabs}'+'\n'+r'\begin{document}'+'\n'+START+'\n'+END+'\n'+r'\end{document}'+'\n'
            main_name='main.tex'
        pre,old,post=template_parts(template)
        if sum(map(len,material))>120000:raise ValueError('写作材料超过12万字符；请精简材料。本流程不会静默截断规范或证据')
        app.checkpoint(t,0,'done');app.checkpoint(t,1);app.event(t,'锁定模板区域、材料边界与交付范围')
        if not any(f.get('characters',0)>0 and f['role'] in ('paper','support') and f['suffix'] not in ('.cls','.sty','.bst','.bib') for f in t['files']):raise ValueError('写作证据无可读文本；请提供方法与真实结果，扫描 PDF 需先 OCR')
        app.checkpoint(t,1,'done');app.checkpoint(t,2);app.event(t,'按真实材料生成 LaTeX 正文；缺失证据明确标注待补充')
        _,loaded=studio.guidance(app.SKILLS,o)
        body=app.model_call('mathm-latex-writing','\n'.join(material),t['topic'],t['year'],writing_options=o)
        app.checkpoint(t,2,'done');app.checkpoint(t,3);app.event(t,'检查模板保真、环境配对、引用键和图片路径')
        validate_body(body,project)
        body=typography.latex_wrap(body,o,pre)
        source=pre+'\n'+body.strip()+'\n'+post
        (project/main_name).write_text(source,encoding='utf-8')
        if o['mode']=='section':(project/'section.tex').write_text(body,encoding='utf-8')
        t['preview']=body
        missing='待补充' in body or 'TODO' in body
        checks=('# LaTeX 写作交付\n\n'
            f'- 字体：西文 {o.get("font_latin","inherit")}；中文 {o.get("font_cjk","inherit")}；字号 {o.get("font_size","inherit")}（inherit=跟随模板；自定义字体使用 XeLaTeX，未验证本机是否安装）。\n- 已保存本任务的补充提示词。\n- 范围：{studio.SECTIONS[o["section"]] if o["mode"]=="section" else "整篇论文"}；类型：{o["paper_kind"]}；语言：{o["language"]}\n- Nature 规则：{len(loaded)}份匹配文件（论文写作/润色及共享规则）。\n- 主文件：{main_name}\n- 仅替换 MATHM_BODY_START / END 之间内容，区域外保持原文。\n'
            '- 已完成：正文格式、环境/花括号配对、正文图片路径、参考文献键静态检查。\n'
            '- 未执行：LaTeX 编译、PDF 逐页审查、页数/字体/页边距核验。源码通过不等于投稿格式合格。\n'
            '- 不执行上传模板；请检查源码后在自己的可信 LaTeX 环境或 Overleaf 中编译。\n'
            + ('- 存在待补充内容：当前为草稿，须补齐后再提交。\n' if missing else '- 论文事实、引用真实性与官方规范仍需作者核验。\n')
            + '- 上传原件和最终包长期保留；解析不落盘；临时目录结束即删，异常残留启动及每小时扫描，超过24小时清理。\n')
        (project/'checks.md').write_text(checks,encoding='utf-8')
        app.checkpoint(t,3,'done');app.checkpoint(t,4)
        with zipfile.ZipFile(scratch/'paper.zip','w',zipfile.ZIP_DEFLATED) as z:
            for f in project.iterdir():z.write(f,f.name)
        app.checkpoint(t,4,'done');app.checkpoint(t,5)
        # Publish only a complete package; no outlines or per-section drafts are exposed.
        (scratch/'paper.zip').replace(folder/'paper.zip')
        (folder/'checks.md').write_text(checks,encoding='utf-8')
        t['artifacts']=[{'name':n,'url':f'/api/tasks/{t["id"]}/artifacts/{n}'} for n in ('paper.zip','checks.md')]
        t['report']=checks;app.checkpoint(t,5,'done');t['status']='completed';app.event(t,'LaTeX 项目已打包；未编译；临时文件已清理')
    except Exception as e:
        t['status']='cancelled' if isinstance(e,InterruptedError) else 'failed'
        for s in t['steps']:
            if s['status']=='running':s['status']='failed'
        app.event(t,str(e)[:300] if isinstance(e,(ValueError,InterruptedError,UnicodeError)) else '写作失败：'+type(e).__name__)
    finally:
        if scratch.exists():shutil.rmtree(scratch)
