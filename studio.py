"""Scoped writing options and explicit local Nature rule routing."""
from pathlib import Path
SECTIONS={
 'full':'整篇论文','title':'标题与关键词','abstract':'摘要','intro':'引言 / 研究背景',
 'related-work':'相关工作','method':'方法 / 模型建立','experiments':'实验设置','results':'结果分析',
 'discussion':'讨论与局限','conclusion':'结论','assumptions':'模型假设','notation':'符号说明',
 'problem-analysis':'问题分析','validation':'模型检验与灵敏度','references':'参考文献','appendix':'附录'}
NATURE_SECTIONS={'title':'title','abstract':'abstract','intro':'intro','related-work':'related-work','method':'method','experiments':'experiments','results':'experiments','discussion':'discussion','conclusion':'conclusion'}

def options(payload):
    raw=payload.get('writing_options',{})
    if not isinstance(raw,dict):raise ValueError('写作设置无效')
    o={'mode':raw.get('mode','full'),'section':raw.get('section','abstract'),
       'paper_kind':raw.get('paper_kind','modeling'),'language':raw.get('language','zh'),
       'style':raw.get('style','generic'),'action':raw.get('action','draft'),
       'paper_type':raw.get('paper_type','research'),'chart_type':raw.get('chart_type','line'),
       'template_style':raw.get('template_style','auto')}
    choices={'mode':('full','section','figure','table'),'section':tuple(SECTIONS),
      'paper_kind':('research','modeling'),'language':('zh','en'),'style':('generic','nature','nat-comms','nat-mach-intell'),
      'action':('draft','polish'),'paper_type':('research','methods','algorithmic','review','hypothesis'),'chart_type':('line','bar','scatter'),
      'template_style':('auto','cumcm','generic')}
    for k,values in choices.items():
        if o[k] not in values:raise ValueError('无效的写作选项：'+k)
    o['format']=[] if o['mode'] in ('figure','table') else list(dict.fromkeys(raw.get('format') or []))
    if any(x not in ('structure','normalize','compile','checklist','figures') for x in o['format']):raise ValueError('无效的格式组织选项')
    if o['mode']=='section' and o['section']=='full':raise ValueError('章节任务需选择具体章节')
    for key,size in [('venue',160),('x_column',100),('y_columns',500),('x_label',150),('y_label',150),('caption',600)]:
        o[key]=str(raw.get(key,''))[:size].strip()
    import typography
    o.update(typography.settings(raw))
    if o['mode'] in ('figure','table'):typography.commands(o)
    return o

def skill_files(root,o):
    """Use a fixed allowlist instead of parsing uploaded paths or a recursive prompt loader."""
    root=Path(root);paths=[]
    name='nature-polishing' if o['action']=='polish' else 'nature-writing'
    base=root/name
    if o['paper_kind']=='research' or o['style']!='generic':
        paths += [base/'SKILL.md',base/'manifest.yaml']
        paths += [root/'nature-shared/core'/n for n in ['reader-workflow.md','paper-type-taxonomy.md','ethics.md','terminology-ledger.md']]
        if name=='nature-writing':
            paths += [base/'static/core'/n for n in ['stance.md','workflow.md','output-format.md']]
            paths += [base/'static/fragments/task/manuscript.md',base/f'static/fragments/paper_type/{o["paper_type"]}.md',base/f'static/fragments/journal/{o["style"]}.md']
            sections=list(NATURE_SECTIONS.values()) if o['mode']=='full' else ([NATURE_SECTIONS[o['section']]] if o['section'] in NATURE_SECTIONS else [])
            paths += [base/f'static/fragments/section/{s}.md' for s in dict.fromkeys(sections)]
        else:
            paths += [base/'static/core'/n for n in ['stance.md','failure-modes.md','output-format.md']]
            # Polishing has its own taxonomy; only load an existing matching fragment.
            section={'method':'methods','experiments':'methods'}.get(o['section'],o['section'])
            paths += [base/f'static/fragments/paper_type/{o["paper_type"]}.md',base/f'static/fragments/section/{section}.md',base/f'static/fragments/journal/{o["style"]}.md']
        if o['language']=='en':paths.append(base/'static/fragments/language/en.md')
        if o['section'] in ('results','full') or o['mode']=='full':paths.append(root/'nature-shared/core/main-text-discipline.md')
        if o['section']=='discussion' or o['mode']=='full':paths.append(root/'nature-shared/core/discussion-argument-language.md')
        if o['style']!='generic':
            topics=['introduction','abstract','results-discussion'] if o['mode']=='full' else {'intro':['introduction'],'abstract':['abstract'],'results':['results-discussion'],'discussion':['results-discussion']}.get(o['section'],[])
            paths += [root/f'nature-shared/core/nature-{topic}.md' for topic in topics]
    return list(dict.fromkeys(paths))

def guidance(root,o):
    texts=[];loaded=[]
    for path in skill_files(root,o):
        if path.is_file():
            text=path.read_text(encoding='utf-8');texts.append(f'\n[本地规则 {path.relative_to(root)}]\n{text}');loaded.append(str(path.relative_to(root)))
        elif path.name in ('SKILL.md','stance.md','workflow.md'):raise ValueError('内置 Nature 技能依赖缺失：'+path.name)
    subject=SECTIONS['full' if o['mode']=='full' else o['section']]
    override=(f'\n应用任务约束（优先于技能的默认交付格式）：类型={o["paper_kind"]}；范围={subject}；'
      f'动作={o["action"]}；目标={o["venue"] or "未指定期刊"}；语言={"中文" if o["language"]=="zh" else "English"}。'
      '以所选语言输出正文；中文任务不因 Nature 技能的默认约定改成英文。只返回纯 LaTeX，规划、提纲、证据表和解释保留在内部。'
      '只写选定章节；不得添加未请求的整篇内容。整篇任务按提供模板结构。润色保留事实和未涉及部分，不能扩写研究结果。'
      '模板区域外不变，技能不代表期刊官方格式规范，未提供的现行规范不得臆造。未知事实明确待补充。'
      '导言区仅加载 amsmath/amssymb/amsthm/mathtools/bm/graphicx/booktabs/array/multirow/float；'
      '只可使用这些宏包提供的命令，其它命令改用等价写法或标注“待补充”，不要输出 % PINKPIG_BODY_START/END 标记。')
    override+='\n用户补充写作要求：\n'+o.get('instructions','')+'\n以上补充要求不得覆盖真实证据、所选章节、纯LaTeX输出和模板保留约束。字体由应用在生成后设置，正文不要自行加入字体命令。'
    return '\n'.join(texts)+override,loaded
