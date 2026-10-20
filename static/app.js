'use strict';
const $=s=>document.querySelector(s);let tasks=[],projects=[],selected=null,project=null,step=2,caps={},busy=false,taskSignature="",projectSignature="",uploads=[],activeView='workspace';
const states={queued:'排队中',running:'处理中',completed:'已完成',failed:'处理失败',interrupted:'已中断',cancelled:'已取消'};
const STAGE={scoping:'准备开始',material:'材料就绪',mainline:'主线已整理',outline:'提纲已生成',drafting:'全文写作中',figures:'图表整理中',polishing:'润色中',checking:'已检查',typesetting:'排版中',done:'已导出'};
const names={'nature-writing':'Nature 科研写作','nature-polishing':'Nature 学术润色','nature-figure':'Nature 科研配图','mathm-latex-writing':'模板约束 LaTeX 写作','pinkpig-latex-writing':'模板约束 LaTeX 写作','math-modeling-skill':'通用数模全流程','hwb-modeling-workflow':'工作流总控','hwb-problem-translator':'题意拆解','hwb-modeling-ideas':'建模路线','hwb-model-dictionary':'模型适配','hwb-abstract-checker':'摘要检查','hwb-model-solution-checker':'模型与结果','hwb-reference-appendix-checker':'引用与附录','hwb-review-paper':'综合评审','hwb-ai-usage-disclosure':'AI使用披露','hwb-cpgmcm-award-standing':'竞赛位置参考','hwb-model-assumption-checker':'模型假设','hwb-paper-aigc-auditor':'写作与模板风险','hwb-paper-format-checker':'论文格式','hwb-problem-analysis-checker':'问题分析','hwb-problem-restatement':'问题重述','hwb-symbol-notation-checker':'符号检查','hbmu-journal-format':'期刊排版 · 湖北民族大学学报（自然科学版）'};
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}
function notify(text){$('#toast').textContent=text;$('#toast').style.display='block';clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('#toast').style.display='none',4500)}
async function api(path,opts={}){const res=await fetch(path,opts);const data=await res.json();if(!res.ok)throw Error(data.error||'请求失败');return data}
function post(path,data={}){return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})}
function view(which){activeView=which;for(const n of ['workspace','projectsView','skillsView','settingsView'])$('#'+n).classList.toggle('hidden',n!==which);for(const [id,v]of [['navTasks','workspace'],['navProjects','projectsView'],['navSkills','skillsView'],['navSettings','settingsView']])$('#'+id).classList.toggle('active',v===which);$('#pageName').textContent={workspace:'任务工作台',projectsView:'论文项目',skillsView:'技能库',settingsView:'模型连接'}[which];if(which==='projectsView'){renderProjectList();if(project)renderProjectDetail()}}

/* ---------------- task workspace (unchanged flows, writing view removed) ---------------- */
function renderTasks(){
 $('#total').textContent=tasks.length;$('#taskCount').textContent=tasks.length;$('#running').textContent=tasks.filter(t=>['running','queued'].includes(t.status)).length;$('#completed').textContent=tasks.filter(t=>t.status==='completed').length;
 const list=$('#taskList');list.replaceChildren();const filter=$('#filter').value;
 const items=tasks.filter(t=>filter==='all'||(filter==='running'?['queued','running'].includes(t.status):filter==='failed'?['failed','cancelled','interrupted'].includes(t.status):t.status===filter));
 if(!items.length){list.append(el('div','list-empty',tasks.length?'这个分类下还没有任务':'还没有研究任务\n点击「新建研究任务」上传第一份材料'));return}
 for(const t of items){const b=el('button','task-card'+(selected===t.id?' selected':''));b.append(el('div','task-title',t.name));const meta=el('div','task-meta');meta.append(el('span','',({review:'论文审查',reading:'读题建模',solving:'通用数模求解',compare:'对标对比',writing:'论文写作'})[t.flow]||t.flow),el('span','badge '+t.status,states[t.status]||t.status));b.append(meta);const bar=el('div','progress'),fill=el('div');fill.style.width=t.progress+'%';bar.append(fill);b.append(bar);const bottom=el('div','task-meta');bottom.append(el('span','',new Date(t.created_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})),el('span','',t.engine==='ai'?'AI技能审查':'本地基础检查'));b.append(bottom);b.onclick=()=>{selected=t.id;renderTasks();renderDetail(t)};list.append(b)}
}
function renderDetail(t,target='taskDetail'){
 if(!t)return;const panel=$('#'+target);panel.replaceChildren();const head=el('div','detail-head'),top=el('div','detail-top');top.append(el('h2','',t.name),el('span','badge '+t.status,states[t.status]||t.status));head.append(top,el('p','',t.message));const bar=el('div','progress'),fill=el('div');fill.style.width=t.progress+'%';bar.append(fill);head.append(bar,el('p','',`${t.progress}% · 按完成步骤计算，非预计剩余时间`));panel.append(head);const body=el('div','detail-body'),steps=el('ol','steps');
 t.steps.forEach((s,i)=>{const row=el('li','step '+s.status);row.append(el('span','step-icon',s.status==='done'?'✓':s.status==='skipped'?'–':String(i+1)),el('span','',s.name),el('small','',({pending:'未开始',running:'进行中',done:'已完成',skipped:'未调用',failed:'失败',interrupted:'已中断'})[s.status]||s.status));steps.append(row)});body.append(steps);
 if(t.status==='failed'||t.status==='interrupted')body.append(el('p','error-note',t.message));
 body.append(el('div','section-caption','材料与解析范围'));
 for(const f of t.files){const n=el('div','file-evidence');n.append(el('div','',f.name),el('small','',`${(f.size/1024).toFixed(1)} KB · ${{paper:'论文',problem:'赛题',rules:'规范',support:'支撑材料',template:'模板'}[f.role]}${f.characters!==undefined?' · 提取 '+f.characters+' 字符':''}`));if(f.notes?.length)n.append(el('div','',f.notes.join('；')));body.append(n)}
 if(t.artifacts.length){const actions=el('div','action-row');const labels={'figure.zip':'下载图片与源文件 ↓','table.zip':'下载 LaTeX 表格 ↓','figure.png':'下载预览图 ↓','paper.zip':'下载 LaTeX 项目 ↓','checks.md':'下载检查说明 ↓','report.md':'下载完整报告 ↓','comparison.md':'下载对标对比报告 ↓','comparison.zip':'下载对比成果包 ↓','solution-summary.md':'下载求解结果说明 ↓','solver.py':'下载求解脚本 ↓','local-results.md':'下载本机数值结果 ↓','descriptive.csv':'下载描述统计 CSV ↓'};for(const a of t.artifacts){const link=el('a','secondary',labels[a.name]||((names[a.name.replace('.md','')]||a.name)+' ↓'));link.href=a.url;link.download=a.name;actions.append(link)}body.append(actions)}
 if(t.preview){body.append(el('div','section-caption','LaTeX 成果预览'),el('pre','report source-preview',t.preview))}
 if(t.writing_options?.mode==='figure'&&t.status==='completed'){const image=el('img','figure-preview');image.src=`/api/tasks/${t.id}/artifacts/figure.png`;image.alt='由上传 CSV 生成的数据图';body.append(image)}
 if(t.report){body.append(el('div','section-caption',t.flow==='compare'?'对标对比报告':'审查报告'),el('pre','report',t.report))}
 const actions=el('div','action-row');if(['running','queued'].includes(t.status)){const b=el('button','secondary','取消任务');b.onclick=()=>taskAction(t.id,'cancel');actions.append(b)}if(['failed','interrupted','cancelled'].includes(t.status)){const b=el('button','secondary','使用原材料重试');b.onclick=()=>taskAction(t.id,'retry');actions.append(b)}body.append(actions);
 if(t.events.length){body.append(el('div','section-caption','处理记录'));const logs=el('div','logs');for(const e of t.events.slice(-10))logs.append(el('div','',new Date(e.time).toLocaleTimeString('zh-CN')+'　'+e.message));body.append(logs)}panel.append(body)
}
async function taskAction(id,action){try{const r=await post(`/api/tasks/${id}/${action}`);if(r.message)notify(r.message);await refresh()}catch(e){notify(e.message)}}
async function refresh(){try{const incoming=await api('/api/tasks');const signature=JSON.stringify(incoming);if(signature===taskSignature){$('#connection').textContent='本地服务已连接'}else{taskSignature=signature;tasks=incoming;if(!selected&&tasks.length)selected=tasks[0].id;renderTasks();const t=tasks.find(x=>x.id===selected);if(t)renderDetail(t)}$('#connection').textContent='本地服务已连接'}catch(e){$('#connection').textContent='本地服务连接中断'}
 if(activeView==='projectsView')await refreshProjects()}

/* ---------------- paper projects ---------------- */
async function refreshProjects(){try{const list=await api('/api/projects');const sig=JSON.stringify(list);if(sig!==projectSignature){projectSignature=sig;projects=list;renderProjectList()}if(project){const fresh=await api('/api/projects/'+project.id);const psig=JSON.stringify(fresh);if(psig!==JSON.stringify(project)){project=fresh;renderProjectDetail()}}}catch(e){}}
function renderProjectList(){const list=$('#projectList');if(!list)return;list.replaceChildren();if(!projects.length){list.append(el('div','list-empty','还没有论文项目\n点击「新建论文项目」开始'));return}for(const p of projects){const b=el('button','project-card'+(project&&project.id===p.id?' selected':''));b.append(el('div','task-title',p.name));const meta=el('div','task-meta');meta.append(el('span','',(p.paper_kind==='modeling'?'数模论文':'科研论文')+' · '+(p.language==='zh'?'中文':'English')),el('span','badge','阶段：'+(STAGE[p.stage]||p.stage)));b.append(meta);b.onclick=()=>openProject(p.id);list.append(b)}}
async function openProject(pid){try{project=await api('/api/projects/'+pid);step=project.mainline? (project.outline?5:3):2;renderProjectList();renderProjectDetail()}catch(e){notify(e.message)}}
async function pAction(suffix,data){const r=await post('/api/projects/'+project.id+suffix,data);project=await api('/api/projects/'+project.id);renderProjectDetail();return r}
function projectActionButton(label,fn,cls){const b=el('button',cls||'primary',label);b.onclick=fn;return b}
function jobBanner(){const job=project.active_job;if(!job)return null;const box=el('div','panel job-banner '+job.status);box.append(el('div','job-title','作业：'+(job.message||job.status)));const bar=el('div','progress'),fill=el('div');fill.style.width=(job.progress||0)+'%';bar.append(fill);box.append(bar);if(job.events?.length)box.append(el('p','hint',job.events.slice(-1)[0].message));if(['queued','running'].includes(job.status))box.append(projectActionButton('取消作业',()=>pAction('/jobs/'+job.id+'/cancel',{}),'secondary'));return box}
function renderProjectDetail(){const panel=$('#projectDetail');if(!project){return}panel.replaceChildren();
 const head=el('div','detail-head'),top=el('div','detail-top');top.append(el('h2','',project.name),el('span','badge','阶段：'+(STAGE[project.stage]||project.stage)));head.append(top,el('p','hint',(project.paper_kind==='modeling'?'数模论文':'科研论文')+' · '+(project.language==='zh'?'中文':'English')+(project.venue?' · '+project.venue:'')+(project.event?' · '+project.event:'')));panel.append(head);
 const jb=jobBanner();if(jb)panel.append(jb);
 const nav=el('nav','step-nav');[['1','项目'],['2','材料与模板'],['3','研究主线'],['4','全文提纲'],['5','全文写作'],['6','图表'],['7','润色'],['8','全文检查'],['9','排版导出']].forEach(([n,t])=>{const b=el('button','step-tab'+(String(step)===n?' active':''),n.padStart(2,'0')+' '+t);b.onclick=()=>{step=Number(n);renderProjectDetail()};nav.append(b)});panel.append(nav);
 const body=el('div','detail-body');panel.append(body);
 ({1:renderStepInfo,2:renderStepUploads,3:renderStepMainline,4:renderStepOutline,5:renderStepWriting,6:renderStepFigures,7:renderStepPolish,8:renderStepCheck,9:renderStepBuild}[step]||renderStepInfo)(body);
}
function field(parent,label,node){const w=el('label','',label);w.append(node);parent.append(w);return node}
function ta(value,placeholder,max){const t=el('textarea');t.value=value||'';if(placeholder)t.placeholder=placeholder;if(max)t.maxLength=max;return t}
function inp(value,placeholder,max){const i=el('input');i.value=value||'';if(placeholder)i.placeholder=placeholder;if(max)i.maxLength=max;return i}

/* step 1 */
function renderStepInfo(b){b.append(el('h3','','项目信息'));const name=inp(project.name,'',100),venue=inp(project.venue,'目标期刊',160),event=inp(project.event,'比赛届次',160);field(b,'论文名称',name);field(b,'目标期刊',venue);field(b,'比赛届次',event);b.append(el('p','hint','一个项目对应一篇论文。阶段：'+Object.values(STAGE).join(' / ')));
 b.append(projectActionButton('保存信息',()=>pAction('/update',{name:name.value,venue:venue.value,event:event.value})));
}

/* step 2 */
function zoneCard(title,hint,zone,b){
 const card=el('div','zone-card');card.append(el('div','zone-head',title),el('p','hint',hint));
 const list=el('div','zone-list');card.append(list);
 const files=project.files.filter(f=>f.zone===zone);
 for(const f of files){const row=el('div','file-evidence');row.append(el('div','',f.name),el('small','',`${(f.size/1024).toFixed(1)} KB · ${{problem:'赛题',paper:'初稿/论文',rules:'规范',support:'支撑材料',reference:'参考文献',template:'模板'}[f.role]||f.role} · ${f.purpose||'（无用途说明）'}`));const rm=el('button','secondary','移除');rm.onclick=()=>pAction('/files/'+f.id+'/delete',{});row.append(rm);list.append(row)}
 const input=el('input');input.type='file';input.multiple=true;input.setAttribute('aria-label',title+'上传');
 const purpose=zone==='material'?inp('','一句用途说明，例如：结果数据用于结果分析'):null;
 input.onchange=async()=>{try{const arr=[];for(const file of input.files){if(file.size>60*1024*1024){notify(file.name+'超过60MB');continue}arr.push({name:file.name,content:await readBase64(file),purpose:purpose?purpose.value:''})}if(!arr.length)return;await pAction('/files',{zone,files:arr});notify('已上传 '+arr.length+' 个文件')}catch(e){notify(e.message)}finally{input.value=''}};
 if(purpose)field(card,'上传用途说明（研究材料必填）',purpose);
 card.append(input);b.append(card);
}
function renderStepUploads(b){
 b.append(el('h3','','材料、模板与格式要求'));
 const grid=el('div','zone-grid');b.append(grid);
 zoneCard('① 研究材料','赛题/问题说明、方法与结果、初稿、数据与参考文献；每个文件填写一句用途说明。','material',grid);
 zoneCard('② 论文模板','LaTeX 项目 ZIP / 单个 .tex / .docx / PDF 示例；上传后显示模板检查。','template',grid);
 zoneCard('③ 格式要求','上传规范文件（PDF/DOCX/TXT/MD），并在下方直接输入补充要求。','rules',grid);
 zoneCard('④ 参考文献','上传 .bib，或提供真实条目；缺来源会标记待补充，不生成假文献。','reference',grid);
 if(project.template){const t=project.template;const box=el('div','panel');box.append(el('h3','','模板检查：'+t.name+'（'+t.kind+'）'));
  box.append(el('p','hint','主文件：'+(t.main||'未确定')+' · 可写区间：'+({markers:'标记位置',document:'document 环境（需人工确认）',none:'未找到'}[t.writable_region.kind])+' · 编译建议：'+t.engine_hint));
  if(t.candidates.length>1){const sel=el('select');for(const c of t.candidates){const o=el('option','',c);o.value=c;sel.append(o)}sel.value=t.main||t.candidates[0];field(box,'选择主文件',sel);box.append(projectActionButton('确认主文件',()=>pAction('/template',{main:sel.value})));}
  for(const i of t.issues||[])box.append(el('p','check-opinion '+({must:'must',verify:'verify'}[i.severity]||'should'),i.message));
  if(t.cover?.found)box.append(el('p','hint','模板含封面/声明固定内容（只读，不参与生成、不被覆盖）。'));
  b.append(box);}
 if(project.rules){const r=project.rules;const box=el('div','panel');box.append(el('h3','','格式要求清单'));
  const tab=el('div','numbering-table');for(const it of r.items){tab.append(el('div','file-evidence',`[${it.source}] ${it.group}：${it.requirement}｜检查方式：文本/源码/编译后，状态：${it.verified==='fulfilled'?'已完成':'未核验'}`))}
  box.append(tab);
  for(const c of r.conflicts||[])box.append(el('p','check-opinion should','冲突（'+c.item+'）：模板='+c.template+'；规范='+c.rules+'；'+c.suggestion));
  const extra=ta(r.extra,'直接输入补充要求，例如：中文宋体、英文 Times New Roman；摘要不超过300字',4000);field(box,'补充要求（可修改）',extra);box.append(projectActionButton('保存并重算清单',()=>pAction('/rules',{extra:extra.value})));
  b.append(box);}
 if(project.references){const rf=project.references;const box=el('div','panel');box.append(el('h3','','参考文献登记'),el('p','hint','bib 条目 '+rf.stats.count+' 条；重复键：'+(rf.stats.duplicates.join('、')||'无')));
  for(const m of rf.missing)box.append(el('p','check-opinion must','正文引用了未提供的键：'+m.key));
  if(rf.entries.filter(e=>e.source==='manual').length)box.append(el('p','hint','手工条目来源待补充，不视为已核验。'));
  b.append(box);}
}

/* step 3 */
function renderStepMainline(b){b.append(el('h3','','研究主线'));
 if(!project.mainline){b.append(el('p','hint','尚未整理。点击下方按钮，系统基于已上传材料生成研究问题、方法与假设、已有结果及来源、结论边界与缺失证据。'),projectActionButton('整理研究主线（AI）',()=>pAction('/mainline',{})));return}
 const m=project.mainline;
 const q=ta(m.question,'',1000),me=ta(m.method,'',4000),as=ta((m.assumptions||[]).join('\n'),'每行一条假设',2000),bd=ta(m.bounds,'',1000);
 field(b,'研究问题',q);field(b,'方法与关键假设',me);field(b,'假设（每行一条）',as);field(b,'结论边界',bd);
 b.append(el('h4','','术语与符号'));
 for(const t of m.terms||[])b.append(el('p','file-evidence',`${t.term}（${t.unit||'无单位'}）：${t.definition}`));
 b.append(el('h4','','已有结果及来源'));
 for(const r of m.results||[])b.append(el('p','file-evidence',`${r.claim}（来源：${r.source==='real'?'真实':'未核验'}；证据 ${(r.evidence||[]).length}）`));
 if(m.missing_evidence?.length){b.append(el('h4','','缺失证据'));for(const g of m.missing_evidence)b.append(el('p','check-opinion verify',g))}
 if(m.structured===false)b.append(el('p','check-opinion should','模型返回未结构化，请人工阅读原文。'));
 const row=el('div','action-row');row.append(projectActionButton('保存修改',()=>pAction('/mainline',{action:'save',mainline:Object.assign({},m,{question:q.value,method:me.value,assumptions:as.value.split('\n').filter(Boolean),bounds:bd.value})})),projectActionButton('重新生成',()=>pAction('/mainline',{}),'secondary'));b.append(row);
}

/* step 4 */
function renderStepOutline(b){b.append(el('h3','','全文提纲'));
 if(!project.outline){b.append(el('p','hint','尚未生成。生成后每节会显示要回答的问题、拟用材料、与前后节联系及缺失证据。'),projectActionButton('生成全文提纲（AI）',()=>pAction('/outline',{})));return}
 const items=project.outline.items;
 b.append(el('p','hint','阅读顺序与建议写作顺序（方法与结果先行）：'+(project.outline.writing_order&&project.outline.writing_order.length?'已生成':'—')));
 const wrap=el('div','outline-list');
 items.forEach((it,i)=>{const card=el('div','outline-item');const t=inp(it.title,'标题',120);t.onchange=()=>{it.title=t.value};card.append(el('div','outline-badge','第 '+String(i+1).padStart(2,'0')+' 节 '+((it.uses_materials||[]).length?'· 用 '+it.uses_materials.length+' 份材料':'')),t);if(it.question)card.append(el('p','hint','要回答：'+it.question));if(it.missing_evidence?.length)card.append(el('p','check-opinion verify','缺失证据：'+it.missing_evidence.join('；')));wrap.append(card)});
 b.append(wrap);
 const row=el('div','action-row');row.append(projectActionButton('保存提纲',()=>pAction('/outline',{action:'save',items})),projectActionButton('重新生成',()=>pAction('/outline',{}),'secondary'));b.append(row);
}

/* step 5 */
function renderStepWriting(b){b.append(el('h3','','全文写作'));
 if(!project.outline||!project.outline.items.length){b.append(el('p','hint','请先生成提纲。'));return}
 const layout=el('div','section-layout');
 const tree=el('div','section-tree');const nums=numsFor();
 project.outline.items.forEach(it=>{const sec=project.sections[it.sid];const b2=el('button','section-tree-item'+(sec?' '+sec.status:''));b2.append(el('span','',(nums[it.sid]||'')+' '+it.title),el('small','',sec?({draft:'待采纳草稿',adopted:'已采纳',empty:'空'}[sec.status]||sec.status):'未开始'));b2.onclick=()=>openSection(it.sid);tree.append(b2)});
 layout.append(tree);
 const sid=window._sid||project.outline.items.find(it=>project.sections[it.sid])?.sid||project.outline.items[0].sid;
 const editor=el('div','section-editor');const sec=project.sections[sid];
 if(sec){const body=ta(sec.body_latex,'LaTeX 正文',200000);editor.append(el('h4','',sec.title+(sec.status==='draft'?'（待采纳草稿）':'')),body);
  const row=el('div','action-row');row.append(projectActionButton('生成草稿',()=>pAction('/sections/'+sid,{action:'draft'}),'secondary'),projectActionButton('采纳',()=>pAction('/sections/'+sid,{action:'adopt'})),projectActionButton('驳回',()=>pAction('/sections/'+sid,{action:'reject'}),'secondary'),projectActionButton('保存正文',()=>pAction('/sections/'+sid,{action:'update',body:body.value}),'secondary'));editor.append(row);
  if(sec.versions?.length){const vs=el('div','versions');vs.append(el('p','hint','历史版本：'));sec.versions.forEach((v,i)=>{const vb=el('button','secondary','恢复 v'+(i+1)+'（'+v.reason+'）');vb.onclick=()=>pAction('/sections/'+sid,{action:'restore',version_id:v.id});vs.append(vb)});editor.append(vs)}
 }else{editor.append(el('h4','',project.outline.items.find(it=>it.sid===sid)?.title||'章节'),el('p','hint','本节还没有正文。'));const instr=ta('','补充指令，例如：先比较主要指标，再解释差异；不要重复上一节方法描述',2000);field(editor,'补充指令',instr);editor.append(projectActionButton('生成草稿（AI）',()=>pAction('/sections/'+sid,{action:'draft',instruction:instr.value})))}
 layout.append(editor);
 const aside=el('div','section-aside');aside.append(el('h4','','写作助手 · 相关证据'),el('p','hint','已自动带入研究主线、术语与前后文。'));
 const files=project.files.filter(f=>f.role==='paper'||f.role==='support'||f.role==='problem');for(const f of files.slice(0,6))aside.append(el('p','file-evidence',f.name+(f.purpose?'（'+f.purpose+'）':'')));
 if(project.check_report&&project.check_report.items.some(i=>i.location&&i.location.sid===sid)){aside.append(el('p','hint','本节相关检查项见第 8 步。'))}
 layout.append(aside);
 b.append(layout);
}
function openSection(sid){window._sid=sid;if(step!==5){step=5}renderProjectDetail()}
function numsFor(){const items=project.outline.items;const c=[0,0,0],out={};for(const it of items){const l=Math.max(1,Math.min(3,it.level||1));c[l-1]++;for(let i=l;i<3;i++)c[i]=0;out[it.sid]=c.slice(0,l).join('.')}return out}

/* step 6 */
function renderStepFigures(b){b.append(el('h3','','图表'));
 const list=el('div','figure-registry');for(const f of project.figures){const row=el('div','figure-item');row.append(el('div','',(f.table?'表':'图')+' '+(f.number||'-')+' · '+f.caption));row.append(el('small','',f.kind+(f.source_file_id?' · 源数据':'')+' · label '+f.label));const rm=el('button','secondary','删除');rm.onclick=()=>pAction('/figures',{action:'delete',fid:f.fid});row.append(rm);list.append(row)}
 b.append(list);
 const csvs=project.files.filter(f=>f.suffix==='.csv');
 if(!csvs.length)b.append(el('p','hint','如需用真实数据生成图表，请先在第 2 步上传一份 CSV 数据。'));
 else{const sel=el('select');csvs.forEach(f=>{const o=el('option','',f.name);o.value=f.id;sel.append(o)});const cap=inp('','图题/表题',600),xk=inp('','X 列名'),yk=inp('','Y 列名（逗号分隔）'),asTable=el('input');asTable.type='checkbox';field(b,'数据文件',sel);field(b,'图题/表题',cap);field(b,'X 列名',xk);field(b,'Y 列名',yk);const lb=el('label','consent');lb.append(asTable,el('span','','作为表格（否则为图）'));b.append(lb);b.append(projectActionButton('生成图表',()=>pAction('/figures',{kind:'generated',source_file_id:sel.value,x_column:xk.value,y_columns:yk.value,as_table:asTable.checked,caption:cap.value})));}
 const up=el('input');up.type='file';up.accept='.png,.jpg,.jpeg,.eps';up.onchange=async()=>{try{const file=up.files[0];if(!file)return;await pAction('/figures',{kind:'uploaded',name:file.name,content:await readBase64(file),caption:(prompt('图题')||'')});notify('已插入图片')}catch(e){notify(e.message)}finally{up.value=''}};field(b,'上传现成图片',up);
}

/* step 7 */
function renderStepPolish(b){b.append(el('h3','','分部分润色'));
 const sids=Object.keys(project.sections);if(!sids.length){b.append(el('p','hint','请先在全文写作中生成并采纳章节。'));return}
 const sel=el('select');sids.forEach(sid=>{const o=el('option','',project.outline.items.find(it=>it.sid===sid)?.title||sid);o.value=sid;sel.append(o)});const kind=el('select');[['language','语言润色'],['logic','逻辑与衔接'],['concise','精简表达'],['custom','自定义']].forEach(([v,t])=>{const o=el('option','',t);o.value=v;kind.append(o)});const instr=ta('','具体润色要求，例如：压缩约20%，保留局限性与适用边界，不改结果数值',2000);
 field(b,'目标章节',sel);field(b,'润色类型',kind);field(b,'补充要求',instr);b.append(projectActionButton('生成润色对照（AI）',()=>pAction('/polish',{target:{scope:'section',sid:sel.value},kind:kind.value,instruction:instr.value})));
 const revs=project.revisions.filter(r=>r.status!=='applied').slice(-3).reverse();
 for(const rev of revs){const card=el('div','panel revision-item');card.append(el('h4','',({language:'语言',logic:'逻辑',concise:'精简',custom:'自定义'}[rev.kind]||rev.kind)+' · '+(rev.structured?'':'未结构化，需人工阅读')));
  for(const it of rev.items){const row=el('div','diff-row');row.append(el('div','diff-old',it.original),el('div','diff-new',it.suggestion));row.append(el('small','hint',it.reason+(it.status!=='pending'?'（'+it.status+'）':'')));if(it.status==='pending'){const a=el('button','secondary','接受');a.onclick=()=>pAction('/revisions/'+rev.rid+'/decide',{action:'accept',iid:it.iid});const r=el('button','secondary','拒绝');r.onclick=()=>pAction('/revisions/'+rev.rid+'/decide',{action:'reject',iid:it.iid});row.append(a,r)}card.append(row)}
  if(rev.related?.length){const rl=el('div','related-list');rl.append(el('p','hint','关联修改建议（仅提示，不自动改动其他章节）：'));for(const x of rev.related)rl.append(el('p','check-opinion should','【'+x.sid+'】'+x.proposed_change+'（'+x.reason+'）'));card.append(rl)}
  card.append(el('p','hint','原版本已保留，可撤销。'));b.append(card)}
}

/* step 8 */
function renderStepCheck(b){b.append(el('h3','','全文检查'));
 const use=el('input');use.type='checkbox';use.checked=true;const ck=el('label','consent');ck.append(use,el('span','','同时进行 AI 语义检查（未配置模型时仅做确定性检查）'));b.append(ck);
 b.append(projectActionButton('检查全文',()=>pAction('/check',{use_ai:use.checked,scope:{kind:'full'}})));
 const r=project.check_report;if(!r)return;
 b.append(el('p','hint','模式：'+(r.model_used?'确定性 + AI':'确定性（未调用模型）')+'；输入截断：'+(r.truncated?'是':'否')+'；必须处理 '+r.summary.must+' / 建议 '+r.summary.should+' / 待核验 '+r.summary.verify));
 const groups={must:'必须处理',should:'建议修改',verify:'待人工核验'};
 for(const sev of ['must','should','verify']){const items=r.items.filter(i=>i.severity===sev);if(!items.length)continue;b.append(el('h4','',groups[sev]+'（'+items.length+'）'));for(const i of items){const op=el('p','check-opinion '+sev);const loc=i.location||{};op.textContent='['+i.source+'] '+i.message+(loc.quote?'（'+loc.quote+'）':'')+'　建议：'+i.suggestion;b.append(op)}}
}
/* step 9 */
function renderStepBuild(b){b.append(el('h3','','排版、编译与导出'));
 const engine=caps.latex_engine||'无';b.append(el('p','hint','本机 LaTeX 引擎：'+engine+'；Word 转换：'+(caps.word_export?'可用（需独立方案并核验）':'本机未检测到，不承诺 PDF→Word 保真')));
 b.append(projectActionButton('生成 LaTeX 项目并尝试编译',()=>pAction('/build',{})));
 const bd=project.build;if(bd){b.append(el('div','build-status'));
  b.append(el('div','build-status-row','源码生成：完成（仅替换模板标记区间）'));
  b.append(el('div','build-status-row','编译：'+(bd.artifacts.some(a=>a.name==='paper.pdf')?'成功，已产出 PDF':'未产出 PDF（见 build-report.md）')));
  b.append(el('div','build-status-row','格式检查：见 latex-project.zip 内 figure-audit.md'));
  b.append(el('div','build-status-row','未解决问题：'+((bd.open_issues||[]).length)+' 项'));
  for(const i of bd.open_issues||[])b.append(el('p','check-opinion must',i.message));
  const row=el('div','action-row');for(const a of project.artifacts){const link=el('a','secondary','下载 '+a.name+' ↓');link.href=a.url;link.download=a.name;row.append(link)}b.append(row);}
}

/* ---------------- create-task dialog (solving / review / reading / compare) ---------------- */
function readBase64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('读取文件失败'));reader.readAsDataURL(file)})}
function renderUploads(){const list=$('#uploadList');list.replaceChildren();uploads.forEach((f,i)=>{const row=el('div','uploaded');row.append(el('span','',f.file.name));const select=el('select');select.setAttribute('aria-label',f.file.name+'材料角色');for(const [value,label]of Object.entries({paper:'论文',problem:'赛题',rules:'规范',support:'支撑材料',template:'模板'})){const o=el('option','',label);o.value=value;select.append(o)}select.value=f.role;select.onchange=()=>f.role=select.value;const remove=el('button','','×');remove.type='button';remove.setAttribute('aria-label','移除'+f.file.name);remove.onclick=()=>{uploads.splice(i,1);renderUploads()};row.append(select,remove);list.append(row)});$('#uploadStatus').textContent=uploads.length?`${uploads.length} 个文件 · ${(uploads.reduce((x,f)=>x+f.file.size,0)/1024/1024).toFixed(1)} MB`:'材料准备好后开始'}
function addFiles(files){for(const file of files){if(uploads.length>=12){notify('最多12个文件');break}if(file.size>12*1024*1024){notify(file.name+'超过12MB');continue}if(!/\.(pdf|docx|txt|md|csv|json|py|xlsx|tex|bib|cls|sty|bst|png|jpg|jpeg|eps)$/i.test(file.name)){notify('不支持文件：'+file.name);continue}if(uploads.some(x=>x.file.name===file.name&&x.file.size===file.size))continue;uploads.push({file,role:/题目|赛题|problem/i.test(file.name)?'problem':/规范|规则|rules/i.test(file.name)?'rules':$('#flow').value==='reading'?'problem':$('#flow').value==='review'?'paper':'support'})}renderUploads()}
function syncCreateForm(){const comparing=$('#flow').value==='compare';if(comparing){$('#engine').value='local';$('#engine').disabled=true;$('#consentBox').classList.add('hidden');$('#sandboxBox').classList.add('hidden')}else{$('#engine').disabled=false;$('#consentBox').classList.toggle('hidden',$('#engine').value!=='ai');$('#sandboxBox').classList.toggle('hidden',!($('#flow').value==='solving'&&$('#engine').value==='ai'))}}
$('#taskForm').onsubmit=async e=>{e.preventDefault();$('#formError').textContent='';const submit=$('#submitTask');submit.disabled=true;submit.textContent='正在上传…';try{if(!uploads.length)throw Error('请先上传材料');if(uploads.reduce((n,x)=>n+x.file.size,0)>24*1024*1024)throw Error('文件总大小超过24MB');const files=await Promise.all(uploads.map(async x=>({name:x.file.name,role:x.role,content:await readBase64(x.file)})));const t=await post('/api/tasks',{name:$('#taskName').value,year:$('#year').value,flow:$('#flow').value,engine:$('#engine').value,topic:$('#topic').value,consent:$('#consent').checked,allow_sandbox:$('#allowSandbox').checked,files});selected=t.id;$('#createDialog').close();$('#taskForm').reset();uploads=[];renderUploads();$('#consentBox').classList.add('hidden');view('workspace');await refresh();notify('任务已创建，正在处理实际材料')}catch(e){$('#formError').textContent=e.message}finally{submit.disabled=false;submit.textContent='开始处理 ↗'}};
$('#newTask').onclick=()=>{$('#flow').value='review';syncCreateForm();$('#createDialog').showModal();$('#taskName').focus()};$('#closeDialog').onclick=()=>$('#createDialog').close();$('#fileInput').onchange=e=>{addFiles(e.target.files);e.target.value=''};$('#engine').onchange=()=>syncCreateForm();$('#flow').onchange=()=>syncCreateForm();$('#filter').onchange=renderTasks;
const zone=$('#dropZone');for(const type of ['dragover','dragenter'])zone.addEventListener(type,e=>{e.preventDefault();zone.classList.add('drag')});zone.addEventListener('dragleave',()=>zone.classList.remove('drag'));zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('drag');addFiles(e.dataTransfer.files)});

/* project dialog + nav */
$('#navTasks').onclick=()=>view('workspace');$('#navProjects').onclick=()=>view('projectsView');$('#navSkills').onclick=()=>view('skillsView');$('#navSettings').onclick=()=>view('settingsView');
$('#newProject').onclick=()=>{$('#projectForm').reset();$('#projectFormError').textContent='';$('#projectDialog').showModal();$('#pName').focus()};
$('#closeProjectDialog').onclick=()=>$('#projectDialog').close();
$('#projectForm').onsubmit=async e=>{e.preventDefault();$('#projectFormError').textContent='';const btn=$('#submitProject');btn.disabled=true;try{const p=await post('/api/projects',{name:$('#pName').value,paper_kind:$('#pKind').value,language:$('#pLanguage').value,venue:$('#pVenue').value,event:$('#pEvent').value,stage:$('#pStage').value,topic:$('#pTopic').value});$('#projectDialog').close();await refreshProjects();await openProject(p.id);notify('项目已创建')}catch(err){$('#projectFormError').textContent=err.message}finally{btn.disabled=false}};

/* ---------------- model connection ---------------- */
const PRESETS={openai:{base:'https://api.openai.com/v1',model:'gpt-4o-mini'},deepseek:{base:'https://api.deepseek.com/v1',model:'deepseek-chat'},qwen:{base:'https://dashscope.aliyuncs.com/compatible-mode/v1',model:'qwen-plus'},zhipu:{base:'https://open.bigmodel.cn/api/paas/v4',model:'glm-4-plus'},ollama:{base:'http://127.0.0.1:11434/v1',model:'qwen2.5'},custom:{base:'',model:''}};
function syncModelLabels(){const ready=caps.ai_ready&&caps.model;$('#modelState').textContent=ready?'模型已配置：'+caps.model:'尚未配置模型'}
function applyModelConfig(c){caps.base_url=c.base_url;caps.model=c.model;caps.has_key=c.has_key;caps.api_key_masked=c.key_masked;caps.env_file=c.env_file;caps.ai_ready=c.has_key;syncModelLabels()}
async function loadModelConfig(){try{const c=await api('/api/model/config');$('#modelBase').value=c.base_url;$('#modelName').value=c.model;$('#modelKey').value='';$('#modelKey').placeholder=c.has_key?('当前密钥 '+c.key_masked+'，留空不修改'):'填写服务商 API Key';$('#modelMeta').textContent='配置文件：'+c.env_file+' · '+(c.has_key?'密钥已配置':'尚未配置密钥');$('#modelPreset').value=Object.keys(PRESETS).find(k=>PRESETS[k].base===c.base_url)||'custom'}catch(e){notify(e.message)}}
$('#modelPreset').onchange=()=>{const p=PRESETS[$('#modelPreset').value];if(p&&$('#modelPreset').value!=='custom'){$('#modelBase').value=p.base;$('#modelName').value=p.model}};
$('#modelFetch').onclick=async()=>{const b=$('#modelFetch');b.disabled=true;b.textContent='获取中…';try{const r=await post('/api/model/models');if(!r.ok)throw Error(r.message);const list=$('#modelList');list.replaceChildren();for(const m of r.models){const o=el('option','',m);o.value=m;list.append(o)}list.classList.remove('hidden');$('#modelName').value=r.models[0];$('#modelResult').textContent='已获取 '+r.models.length+' 个模型，可在下拉中选择。'}catch(e){$('#modelResult').textContent='拉取失败：'+e.message}finally{b.disabled=false;b.textContent='拉取模型'}};
$('#modelList').onchange=()=>{$('#modelName').value=$('#modelList').value};
$('#modelSave').onclick=async()=>{const b=$('#modelSave');b.disabled=true;try{const c=await post('/api/model/config',{base_url:$('#modelBase').value,model:$('#modelName').value,api_key:$('#modelKey').value});applyModelConfig(c);$('#modelResult').textContent='已保存并生效，无需重启。';await loadModelConfig()}catch(e){$('#modelResult').textContent='保存失败：'+e.message}finally{b.disabled=false}};
$('#modelTest').onclick=async()=>{const b=$('#modelTest');b.disabled=true;$('#modelResult').textContent='正在保存并测试…';try{const c=await post('/api/model/config',{base_url:$('#modelBase').value,model:$('#modelName').value,api_key:$('#modelKey').value});applyModelConfig(c);await loadModelConfig();const r=await post('/api/model/test');$('#modelResult').textContent=r.ok?('连接成功：'+r.model+'（'+(r.latency_ms??'-')+' ms）'):('连接失败：'+r.message)}catch(e){$('#modelResult').textContent='测试失败：'+e.message}finally{b.disabled=false}};
$('#modelClear').onclick=async()=>{if(!confirm('清除本机保存的模型密钥？'))return;try{const c=await post('/api/model/config',{base_url:$('#modelBase').value,model:$('#modelName').value,clear_key:true});applyModelConfig(c);$('#modelResult').textContent='密钥已清除。';await loadModelConfig()}catch(e){$('#modelResult').textContent='清除失败：'+e.message}};

async function start(){try{caps=await api('/api/capabilities');loadModelConfig();$('#skillCount').textContent=caps.skills.length;$('#skillsTotal').textContent=caps.skills.length;$('#modelState').textContent=caps.ai_ready&&caps.model?'模型已配置：'+caps.model:'尚未配置模型';$('#dataDirectory').textContent='本地材料目录：'+caps.data_directory;$('#parserState').textContent=`文档解析：PDF ${caps.parser_pdf?'已就绪':'需安装依赖'} / DOCX ${caps.parser_docx?'已就绪':'需安装依赖'}`;for(const s of caps.skills){const card=el('div','panel skill-card');card.append(el('h2','',names[s]||s),el('code','',s),el('p','',(caps.skill_families?.modeling||[]).includes(s)?'已接入数模求解 / 审查流程':(caps.skill_families?.writing||[]).includes(s)?'已接入论文项目与写作':'已安装 · 暂未开放独立运行'));$('#skillGrid').append(card)}if(!caps.ai_ready||!caps.model)$('#engine option[value="ai"]').textContent='AI技能审查 · 请先配置模型'}catch(e){notify(e.message)}await refresh();setInterval(refresh,2000)}start();
