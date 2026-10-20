"""Template-bounded writing with optional structure, reference, checklist and compile/layout steps."""
import re, shutil, subprocess, sys, threading, time, zipfile
from collections import Counter
from pathlib import Path
# Canonical body markers; the legacy MATHM markers are still accepted for existing templates.
MARKERS=[('% PINKPIG_BODY_START', '% PINKPIG_BODY_END'), ('% MATHM_BODY_START', '% MATHM_BODY_END')]
START,END=MARKERS[0]
BUILD_SUFFIXES={'.aux','.log','.fls','.fdb_latexmk','.out','.toc','.bbl','.blg','.nav','.snm','.synctex','.xdv'}
EXPECTED_SECTIONS={'modeling':['摘要','问题分析','模型假设','符号说明','模型建立','结果分析','模型检验','结论','参考文献','附录'],
                   'research':['摘要','引言','相关工作','方法','实验','结果','讨论','结论','参考文献','附录']}
# Packages the generated shell loads; the model is told to stay within them.
PACKAGES=r'\usepackage{amsmath,amssymb,amsthm,mathtools,bm,graphicx,booktabs,array,multirow,float}'
# Define macros that competition classes (e.g. cumcmthesis) provide, so a plain shell still compiles.
SHIMS=r'\providecommand{\keywords}[1]{\par\noindent\textbf{关键词：}#1}'+'\n'+r'\providecommand{\keyword}[1]{\keywords{#1}}'
_cleanup_roots=set()

def template_parts(text):
    for start,end in MARKERS:
        if text.count(start)!=1 or text.count(end)!=1:continue
        pre,rest=text.split(start);body,post=rest.split(end)
        if r'\begin{document}' not in pre or r'\end{document}' not in post:
            raise ValueError('写作区域必须在 document 环境内，不能覆盖导言区或封面')
        return pre+start,body,end+post
    raise ValueError('主模板须各包含一次 % PINKPIG_BODY_START 和 % PINKPIG_BODY_END（兼容旧 MATHM 标记），放在 document 内指定正文位置；可下载示例模板')

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
    threading.Thread(target=loop,daemon=True,name='pinkpig-cleanup').start()

def extract_body(raw):
    """Accept code fences or echoed body markers and return only the LaTeX payload."""
    text=(raw or '').strip()
    fenced=re.findall(r'```[a-zA-Z]*\s*\n(.*?)```', text, re.S)
    if fenced: text=max(fenced,key=len).strip()
    for start,end in MARKERS:
        if start in text and end in text:
            text=text.split(start,1)[1].split(end,1)[0].strip(); break
    return text

def validate_body(body, project, images=None, bibkeys=None):
    issues=[]
    if not body.strip():issues.append('正文为空')
    if '```' in body:issues.append('含代码围栏')
    if any(marker in body for pair in MARKERS for marker in pair):issues.append('含区域标记')
    if issues:raise ValueError('模型未返回纯 LaTeX 正文（'+'、'.join(issues)+'，请重试）。原文开头：'+body[:120].replace('\n',' '))
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
        if images is not None:
            if Path(value).name not in images:raise ValueError('模型引用了未提供的图片：'+value)
        elif not any((project/(value+ext)).is_file() for ext in ('','.pdf','.png','.jpg','.jpeg','.eps')):
            raise ValueError('模型引用了未提供的图片：'+value)
    known=set(bibkeys) if bibkeys is not None else set()
    if bibkeys is None:
        for p in project.glob('*.bib'):
            known.update(re.findall(r'@\w+\s*\{\s*([^,\s]+)',p.read_text(encoding='utf-8-sig')))
    known.update(re.findall(r'\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}',code))
    for keys in re.findall(r'\\cite\w*\*?(?:\[[^\]]*\])*\{([^}]+)\}',code):
        if any(k.strip() not in known for k in keys.split(',')):raise ValueError('模型使用了未提供的参考文献键：'+keys)

def organize_structure(body, o):
    """Numbering derived from the real body; the expected-section list is a labelled heuristic, not a spec."""
    levels={'section':1,'subsection':2,'subsubsection':3}
    entries=[(levels[m[1]],m[2].strip()) for m in re.finditer(r'\\(section|subsection|subsubsection)\*?\{([^}]*)\}',body)]
    counters=[0,0,0];lines=[]
    for level,title in entries:
        counters[level-1]+=1
        for i in range(level,3):counters[i]=0
        lines.append('  '*(level-1)+'.'.join(str(counters[i]) for i in range(level))+' '+title)
    report='# 章节结构组织\n\n按正文实际标题命令生成的层级与编号：\n\n'+(('\n'.join(lines)) if lines else '正文未检出 \\section 等标题命令，未能组织章节结构。')
    present=re.sub(r'\s+','',body)
    missing=[name for name in EXPECTED_SECTIONS.get(o.get('paper_kind'),[]) if name not in present]
    if missing:report+='\n\n## 该论文类型的常规章节中尚未出现\n\n'+'\n'.join('- '+n for n in missing)+'\n\n仅为按论文类型的常规建议，非官方规范；请以上传的规范为准。'
    return report

def normalize_references(body, project, bib_texts=None):
    """Deterministic key cleanup only: no content rewriting, no source verification."""
    changes=[]
    def fix(m):
        cmd,brackets,keys=m[1],m[2],m[3]
        ordered=sorted(dict.fromkeys(k.strip() for k in keys.split(',') if k.strip()))
        rebuilt='\\'+cmd+brackets+'{'+','.join(ordered)+'}'
        if rebuilt!=m[0]:changes.append(f'{m[0]} → {rebuilt}')
        return rebuilt
    new=re.sub(r'\\(cite\w*\*?)((?:\[[^\]]*\])*)\{([^}]+)\}',fix,body)
    keys=Counter()
    if bib_texts is not None:
        for text in bib_texts:keys.update(re.findall(r'@\w+\s*\{\s*([^,\s]+)',text))
    else:
        for p in project.glob('*.bib'):keys.update(re.findall(r'@\w+\s*\{\s*([^,\s]+)',p.read_text(encoding='utf-8-sig')))
    keys.update(re.findall(r'\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}',new))
    notes=['参考文献存在重复键：'+', '.join(k for k,c in keys.items() if c>1)] if any(c>1 for c in keys.values()) else []
    for env in ('figure','table'):
        for m in re.finditer(r'\\begin\{'+env+r'\}(.*?)\\end\{'+env+r'\}',new,re.S):
            if '\\caption' not in m[1] and '\\label' in m[1]:notes.append(f'{env} 环境中出现 \\label 但缺少 \\caption，编号可能异常')
    report='# 引用与图表题注整理\n\n'+('\n'.join('- '+c for c in changes[:50]) if changes else '- 引用键无需改写：已去重并归一空格。')+'\n'
    if notes:report+='\n'+'\n'.join('- '+n for n in notes)+'\n'
    report+='\n仅做确定性整理（去重、排序、空格归一、题注顺序提示）；未改写引用内容，未核验文献真实性。\n'
    return new,report

def _zi(text):
    """Chinese-context word count, matching check_layout.py's convention."""
    t=re.sub(r'\\[a-zA-Z]+\s*',' ',text);t=re.sub(r'[{}$~^_\\&%#]',' ',t)
    return len(re.findall(r'[\u4e00-\u9fff]',t))+len(re.findall(r'[A-Za-z0-9]+(?:[.,][0-9]+)*',t))

def _brace_arg(text, start):
    """Return the content inside the first {...} group beginning at/after ``start``."""
    i=text.find('{',start)
    if i<0:return None
    depth=0;buf=[]
    while i<len(text):
        c=text[i]
        if c=='{':depth+=1
        elif c=='}':
            depth-=1
            if depth==0:return ''.join(buf)
        if depth>=1 and not (depth==1 and c=='{'):buf.append(c)
        i+=1
    return None

def audit_figures_tables(body, project, o):
    """Deterministic, model-free audit of figure/table structure, captions and references.

    Reports orphans, missing captions/labels, duplicate labels and caption length; it
    never rewrites content or invents citations or data.
    """
    envs=[]
    for env in ('figure','table'):
        for m in re.finditer(r'\\begin\{'+env+r'\}(.*?)\\end\{'+env+r'\}',body,re.S):
            envs.append((env,body.count('\n',0,m.start())+1,m.group(1)))
    refs={k.strip() for keys in re.findall(r'\\(?:ref|autoref|eqref|pageref)\{([^}]+)\}',body) for k in keys.split(',')}
    issues=[];labels={};caps=[]
    caption_range=(100,150) if o.get('paper_kind')=='modeling' else None
    for env,lineno,content in envs:
        cap_pos=re.search(r'\\caption(?:\[[^\]]*\])?\s*\{',content)
        cap=_brace_arg(content,cap_pos.start()) if cap_pos else None
        lab_pos=re.search(r'\\label\{',content)
        lab=_brace_arg(content,lab_pos.start()) if lab_pos else None
        if cap is None:issues.append(f'第 {lineno} 行的 {env} 环境缺少 \\caption：请补写题注。')
        else:caps.append((env,lineno,cap))
        if lab is None:issues.append(f'第 {lineno} 行的 {env} 环境缺少 \\label：无法被正文引用，请补 \\label。')
        else:
            labels.setdefault(lab.strip(),[]).append(lineno)
            if lab.strip() not in refs:issues.append(f'第 {lineno} 行的 {env}（label {lab.strip()}）未在正文中被引用（孤儿图表）：请补充“如图/表 N 所示”的引用，或删除该图表。')
    for lab,lines in labels.items():
        if len(lines)>1:issues.append(f'label {lab} 重复出现在第 {lines[0]}、{lines[1]} 行：编号会错乱，请改为唯一标签。')
    if caption_range:
        for env,lineno,cap in caps:
            zi=_zi(cap)
            if not caption_range[0]<=zi<=caption_range[1]:
                issues.append(f'第 {lineno} 行的 {env} 题注 {zi} 字，不在国赛建议区间 {caption_range[0]}–{caption_range[1]} 字：请补充说明比较对象、条件与单位。')
    report='# 图表规范审计\n\n- 共检出 {} 个 figure、{} 个 table。\n\n'.format(sum(1 for e in envs if e[0]=='figure'),sum(1 for e in envs if e[0]=='table'))
    if issues:report+='## 需修复\n\n'+'\n'.join('- '+x for x in issues)+'\n'
    else:report+='## 通过\n\n- 未检出孤儿图表、缺失题注/标签或重复标签。\n'
    report+='\n本审计为确定性静态检查（不核验图片内容与数据真实性）；孤儿图表仅报告并给出修复建议，不会自动生成引用。\n'
    return report


def format_checklist(rules_text, o):
    groups=[('篇幅与页数',['页','字数','篇幅']),('字号与字体',['字号','字体','宋体','Times','黑体','小四','五号']),
            ('页面设置',['页边距','行距','纸张','A4']),('匿名与标识',['匿名','不得出现','学校','姓名']),
            ('摘要与关键词',['摘要','关键词']),('参考文献',['参考文献','引用','著录']),('图表与公式',['图表','图题','表题','公式','编号'])]
    lines=[]
    if not rules_text.strip():
        lines.append('- 未上传本届规范：无法生成可核对的要求清单，以下项全部未核验。')
    for name,words in groups:
        hits=[w for w in words if w in rules_text]
        lines.append(f'- {name}：'+('规范中检出关键词：'+'、'.join(hits) if hits else '规范中未检出相关关键词，需人工确认'))
    return '# 格式检查清单\n\n'+'\n'.join(lines)+f'\n\n清单由上传规范的关键词扫描生成，命中不代表条款一致；未核验项须人工对照官方规范。论文类型：{o.get("paper_kind")}；语言：{o.get("language")}。\n'

def pdf_metrics(pdf):
    try: import pymupdf
    except ImportError: return None
    with pymupdf.open(pdf) as doc:
        sizes=sorted({(round(p.rect.width),round(p.rect.height)) for p in doc})
        fonts=set();near_blank=[]
        for page in doc:
            spans=[s['size'] for b in page.get_text('dict')['blocks'] if b.get('type')==0 for l in b['lines'] for s in l['spans']]
            fonts.update(round(s,1) for s in spans)
            if len(page.get_text().strip())<10:near_blank.append(page.number+1)
        return {'pages':len(doc),'sizes':sizes,'font_sizes':sorted(fonts)[:12],'near_blank':near_blank}

def first_error(log):
    """Pull the first LaTeX error with a little context so the report is actionable."""
    lines=log.splitlines()
    for i,line in enumerate(lines):
        if line.lstrip().startswith('!') or 'LaTeX Error' in line:
            return ' '.join(x.strip() for x in lines[i:i+4] if x.strip())[:500]
    return '未从日志中定位到标准错误行，请查看下方日志尾部。'

def compile_pdf(project, main_name, app):
    """Compile locally; when the toolchain or the compile fails we say so and never claim a verified layout."""
    engine,path=app.latex_engine()
    if not engine:return None,'# PDF 编译与版式检查\n\n- 未找到本机 LaTeX（latexmk/xelatex/pdflatex），未编译，版式未核验。\n'
    if engine=='latexmk':cmd=[path,'-xelatex','-interaction=nonstopmode','-halt-on-error','-no-shell-escape',main_name]
    else:cmd=[path,'-interaction=nonstopmode','-halt-on-error','-no-shell-escape',main_name]
    runs=[cmd] if engine=='latexmk' else [cmd,cmd]
    logs=[];ok=False
    for args in runs:
        try:result=subprocess.run(args,cwd=project,capture_output=True,text=True,timeout=180)
        except (OSError,subprocess.SubprocessError) as e:return None,'# PDF 编译与版式检查\n\n- 编译未能启动：'+type(e).__name__+'，版式未核验。\n'
        logs.append(result.stdout[-3000:]);ok=(project/Path(main_name).with_suffix('.pdf')).exists()
        if not ok and result.returncode:break
    pdf=project/Path(main_name).with_suffix('.pdf')
    if not ok or not pdf.exists():
        log='\n'.join(logs)
        return None,'# PDF 编译与版式检查\n\n- **编译失败，未产出 PDF，版式未核验。**\n- 首个错误：'+first_error(log)+'\n\n```\n'+log[-1500:]+'\n```\n'
    report='# PDF 编译与版式检查\n\n- 使用 '+engine+' 编译成功，产出 '+pdf.name+'。\n'
    metrics=pdf_metrics(pdf)
    if metrics:
        report+=f'- 页数：{metrics["pages"]}；页面尺寸(pt)：{metrics["sizes"]}；正文字号样本(pt)：{metrics["font_sizes"]}\n'
        if metrics['near_blank']:report+='- 近乎空白的页面：'+'、'.join(map(str,metrics['near_blank']))+'（可能为扫描图或排版留白）\n'
    else:report+='- 本机缺少 PyMuPDF，未做页面尺寸与页数核验。\n'
    script=app.SKILLS/'math-modeling-skill/scripts/check_layout.py'
    if script.exists() and metrics:
        # -B only: isolated mode (-I) hides this interpreter's own site-packages, which breaks the script's pymupdf dependency.
        checked=subprocess.run([sys.executable,'-B',str(script),str(pdf),'--tex',str(project/main_name)],capture_output=True,text=True,timeout=120)
        verdict={0:'全部通过',1:'存在需修复项'}.get(checked.returncode,'工具未能运行（退出码 '+str(checked.returncode)+'），本次未核验')
        report+='\n## 版面体检\n\n`check_layout.py`：'+verdict+'\n\n```\n'+(checked.stdout[-3000:] or checked.stderr[-1500:])+'\n```\n'
    else:report+='- 未运行版面体检脚本（缺少脚本或 PyMuPDF），图表占比与题注字数未核验。\n'
    report+='\n编译通过不等于符合官方格式；页边距、字体一致性与提交要求仍需人工核对。\n'
    return pdf,report

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
        material=[];template=None;main_name=None;rules_text=''
        for f in t['files']:
            source=folder/(f['id']+f['suffix'])
            if f['role']=='template':
                template=source.read_text(encoding='utf-8-sig');main_name=f['name'];text=template;notes=[]
            elif f['suffix'] in ('.png','.jpg','.jpeg','.eps'):
                text='';notes=['作为图片资源打包；模型未查看图片内容']
            else:
                text,notes,_=app.extract(source,f['suffix'])
            if f['role']=='rules':rules_text+=text+'\n'
            f.update(characters=len(text),notes=notes)
            material.append(f'\n[文件 {f["name"]}；角色 {f["role"]}]\n{text}')
            if f['suffix'] in ('.tex','.bib','.cls','.sty','.bst','.png','.jpg','.jpeg','.eps') or (f['suffix']=='.pdf' and f['role']=='support'):
                shutil.copy2(source,project/f['name'])
        template_note=None
        if template is None:
            style=o.get('template_style','auto')
            use_cumcm=style=='cumcm' or (style=='auto' and o['paper_kind']=='modeling' and o['language']=='zh')
            cumcm_cls=app.SKILLS/'math-modeling-skill/templates/cumcmthesis/cumcmthesis.cls'
            if use_cumcm and cumcm_cls.exists():
                shutil.copy2(cumcm_cls,project/'cumcmthesis.cls')
                # 该类内部通过 ctex 提供中文支持；cls 已加载 amsmath/amssymb/bm 等并自带
                # \proof 定理环境，故不再加载 amsthm（会与 cls 的 \proof 冲突），仅补 mathtools。
                template=(r'\documentclass[withoutpreface,bwprint]{cumcmthesis}'+'\n'
                          +r'% cumcmthesis 内部加载 ctex 提供中文支持；cleveref/caption/hyperref 由模板提供'+'\n'
                          +r'\usepackage{mathtools}'+'\n'+SHIMS+'\n'
                          +r'\begin{document}'+'\n'+START+'\n'+END+'\n'+r'\end{document}'+'\n')
                main_name='main.tex'
                template_note='已套用国赛 cumcmthesis 模板（withoutpreface,bwprint；需 XeLaTeX 编译）。'
            else:
                if use_cumcm:template_note='未找到 math-modeling-skill 的 cumcmthesis.cls，已回退通用 ctexart；本次未套用国赛模板。'
                cls=r'\documentclass[UTF8,a4paper,12pt]{ctexart}' if o['language']=='zh' else r'\documentclass[a4paper,12pt]{article}'
                if o.get('font_latin','inherit')!='inherit':cls+='\n'+r'\usepackage{fontspec}'
                if o['language']=='en' and o.get('font_cjk','inherit')!='inherit':cls+='\n'+r'\usepackage{xeCJK}'
                template=cls+'\n'+PACKAGES+'\n'+SHIMS+'\n'+r'\begin{document}'+'\n'+START+'\n'+END+'\n'+r'\end{document}'+'\n'
                main_name='main.tex'
        pre,old,post=template_parts(template)
        if sum(map(len,material))>120000:raise ValueError('写作材料超过12万字符；请精简材料。本流程不会静默截断规范或证据')
        app.checkpoint(t,0,'done');app.checkpoint(t,1);app.event(t,'锁定模板区域、材料边界与交付范围')
        if not any(f.get('characters',0)>0 and f['role'] in ('paper','support') and f['suffix'] not in ('.cls','.sty','.bst','.bib') for f in t['files']):raise ValueError('写作证据无可读文本；请提供方法与真实结果，扫描 PDF 需先 OCR')
        app.checkpoint(t,1,'done');app.checkpoint(t,2);app.event(t,'按真实材料生成 LaTeX 正文；缺失证据明确标注待补充')
        _,loaded=studio.guidance(app.SKILLS,o)
        body=extract_body(app.model_call(app.WRITING_SKILL,'\n'.join(material),t['topic'],t['year'],writing_options=o))
        app.checkpoint(t,2,'done');app.checkpoint(t,3);app.event(t,'检查模板保真、环境配对、引用键和图片路径')
        validate_body(body,project)
        fmt=[a for a in o.get('format',[])]
        notes=[]
        if template_note:notes+=[template_note]
        if 'normalize' in fmt:
            body,ref_report=normalize_references(body,project);(project/'reference-report.md').write_text(ref_report,encoding='utf-8');notes+=['引用键与题注已确定性整理。']
        body=typography.latex_wrap(body,o,pre)
        source=pre+'\n'+body.strip()+'\n'+post
        (project/main_name).write_text(source,encoding='utf-8')
        if o['mode']=='section':(project/'section.tex').write_text(body,encoding='utf-8')
        t['preview']=body
        if 'structure' in fmt:
            (project/'structure.md').write_text(organize_structure(body,o),encoding='utf-8');notes+=['已生成章节结构与编号。']
        if 'figures' in fmt:
            (project/'figure-audit.md').write_text(audit_figures_tables(body,project,o),encoding='utf-8');notes+=['已生成图表规范审计。']
        if 'checklist' in fmt:
            (project/'format-checklist.md').write_text(format_checklist(rules_text,o),encoding='utf-8');notes+=['已生成格式检查清单。']
        compiled=None
        if 'compile' in fmt:
            app.event(t,'在本机编译 PDF 并检查版式')
            compiled,layout_report=compile_pdf(project,main_name,app)
            (project/'layout-report.md').write_text(layout_report,encoding='utf-8')
            notes+=['已编译 PDF 并产出《版面体检》。' if compiled else '编译未成功，版式未核验（详见 layout-report.md）。']
        missing='待补充' in body or 'TODO' in body
        checks=('# LaTeX 写作交付\n\n'
            f'- 字体：西文 {o.get("font_latin","inherit")}；中文 {o.get("font_cjk","inherit")}；字号 {o.get("font_size","inherit")}（inherit=跟随模板；自定义字体使用 XeLaTeX）。\n- 已保存本任务的补充提示词。\n- 范围：{studio.SECTIONS[o["section"]] if o["mode"]=="section" else "整篇论文"}；类型：{o["paper_kind"]}；语言：{o["language"]}\n- Nature 规则：{len(loaded)}份匹配文件（论文写作/润色及共享规则）。\n- 主文件：{main_name}\n- 仅替换 PINKPIG_BODY_START / END 之间内容（兼容旧 MATHM 标记），区域外保持原文。\n'
            +('\n'.join('- '+n for n in notes)+'\n' if notes else '')
            +'- 已完成：正文格式、环境/花括号配对、正文图片路径、参考文献键静态检查。\n'
            +('- 已在本机编译并检查版式；编译通过不等于符合官方格式。\n' if compiled else ('- 已尝试在本机编译但未成功（原因见 layout-report.md），版式未核验。\n' if 'compile' in fmt else '- 未执行：LaTeX 编译、PDF 逐页审查、页数/字体/页边距核验。源码通过不等于投稿格式合格。\n'))
            +'- 不执行上传模板；最终版面请在你的可信 LaTeX 环境或 Overleaf 中复核。\n'
            + ('- 存在待补充内容：当前为草稿，须补齐后再提交。\n' if missing else '- 论文事实、引用真实性与官方规范仍需作者核验。\n')
            + '- 上传原件和最终包长期保留；解析不落盘；临时目录结束即删，异常残留启动及每小时扫描，超过24小时清理。\n')
        (project/'checks.md').write_text(checks,encoding='utf-8')
        app.checkpoint(t,3,'done');app.checkpoint(t,4)
        with zipfile.ZipFile(scratch/'paper.zip','w',zipfile.ZIP_DEFLATED) as z:
            for f in sorted(project.iterdir()):
                if f.is_file() and f.suffix.lower() not in BUILD_SUFFIXES and not f.name.endswith('.synctex.gz'):z.write(f,f.name)
        app.checkpoint(t,4,'done');app.checkpoint(t,5)
        # Publish only a complete package; no outlines or per-section drafts are exposed outside it.
        (scratch/'paper.zip').replace(folder/'paper.zip')
        (folder/'checks.md').write_text(checks,encoding='utf-8')
        names=['paper.zip','checks.md']
        if compiled:
            shutil.copy2(compiled,folder/'paper.pdf');names.append('paper.pdf')
        t['artifacts']=[{'name':n,'url':f'/api/tasks/{t["id"]}/artifacts/{n}'} for n in names]
        t['report']=checks;app.checkpoint(t,5,'done');t['status']='completed';app.event(t,'LaTeX 项目已打包；临时文件已清理')
    except Exception as e:
        t['status']='cancelled' if isinstance(e,InterruptedError) else 'failed'
        for s in t['steps']:
            if s['status']=='running':s['status']='failed'
        app.event(t,str(e)[:300] if isinstance(e,(ValueError,InterruptedError,UnicodeError)) else '写作失败：'+type(e).__name__)
    finally:
        if scratch.exists():shutil.rmtree(scratch)
