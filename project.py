"""Project-based paper workspace.

One project == one paper. This module owns persistence, the four upload zones
materials / template / rules / references, the deterministic template & rules &
reference checks, the async AI jobs (mainline / outline / section / polish /
check / build), the figure registry and the LaTeX export. It always takes the
app namespace as its first argument so it can be unit-tested with a stub
namespace (``SimpleNamespace(**vars(app))``) and never imports ``app`` directly.
"""
from __future__ import annotations
import base64, hashlib, json, re, shutil, subprocess, sys, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROLES = ('problem', 'paper', 'rules', 'support', 'reference', 'template')
ZONES = ('material', 'template', 'rules', 'reference')
STAGES = ('scoping', 'material', 'mainline', 'outline', 'drafting', 'figures', 'polishing', 'checking', 'typesetting', 'done')
ALLOWED = {'.pdf', '.docx', '.txt', '.md', '.csv', '.json', '.py', '.xlsx', '.tex', '.bib', '.cls', '.sty', '.bst', '.png', '.jpg', '.jpeg', '.eps', '.zip'}
RESERVED = {'main.tex', 'paper.pdf', 'latex-project.zip', 'checks.md', 'build-report.md', 'figure.png',
            'source-data.csv', 'plot.py', 'settings.json', 'validation.json', 'figure.tex', 'table.tex', 'report.md', 'comparison.md'}
MAX_FILES = 60; MAX_BYTES = 200 * 1024 * 1024; MAX_FILE = 60 * 1024 * 1024
MAX_PAYLOAD_CHARS = 2_000_000
JOB_KINDS = ('mainline', 'outline', 'section', 'polish', 'check', 'build')
JOB_STEPS = {'mainline': ['收集材料', '整理主线', '规则化补缺'],
             'outline': ['收集材料', '生成提纲', '归一与编号'],
             'section': ['准备上下文', '生成草稿', '静态校验'],
             'polish': ['准备上下文', '生成对照', '定位校验'],
             'check': ['确定性检查', 'AI 语义检查', '汇总'],
             'build': ['源码生成', '编译', '格式检查', '未解决问题']}


def now():
    return datetime.now(timezone.utc).isoformat()


def projects_dir(app):
    return app.DATA / 'projects'


def project_dir(app, pid):
    return projects_dir(app) / pid


def build_dir(app, p):
    return project_dir(app, p['id']) / 'build'


def _default_role(zone):
    return {'material': 'support', 'template': 'template', 'rules': 'rules', 'reference': 'reference'}[zone]


# ---------------------------------------------------------------- persistence

def get_project(app, pid):
    with app.db() as c:
        row = c.execute('SELECT payload FROM projects WHERE id=?', (pid,)).fetchone()
    if not row:
        raise ValueError('项目不存在')
    return json.loads(row[0])


def save_project(app, p):
    p['updated_at'] = now()
    payload = json.dumps(p, ensure_ascii=False)
    if len(payload) > MAX_PAYLOAD_CHARS:
        raise ValueError('项目正文超出本地存储预算，请精简或拆分')
    with app.DB_LOCK, app.db() as c:
        c.execute('INSERT OR REPLACE INTO projects VALUES (?,?)', (p['id'], payload))
    return p


def list_projects(app):
    with app.db() as c:
        rows = c.execute('SELECT payload FROM projects').fetchall()
    return sorted([json.loads(r[0]) for r in rows], key=lambda x: x.get('updated_at') or '', reverse=True)


def public_project(p):
    return {k: v for k, v in p.items() if k != 'jobs'}


def create_project(app, payload):
    payload = payload if isinstance(payload, dict) else {}
    name = str(payload.get('name', '')).strip()[:100]
    if not name:
        raise ValueError('请填写论文名称')
    kind = payload.get('paper_kind', 'research'); lang = payload.get('language', 'zh'); stage = payload.get('stage', 'scoping')
    if kind not in ('research', 'modeling'):
        raise ValueError('论文类型无效')
    if lang not in ('zh', 'en'):
        raise ValueError('正文语言无效')
    if stage not in STAGES:
        raise ValueError('当前阶段无效')
    pid = uuid.uuid4().hex
    project_dir(app, pid).mkdir(parents=True, exist_ok=True)
    p = {'id': pid, 'name': name, 'paper_kind': kind, 'language': lang,
         'venue': str(payload.get('venue', ''))[:160], 'event': str(payload.get('event', ''))[:160],
         'stage': stage, 'topic': str(payload.get('topic', ''))[:2000],
         'created_at': now(), 'updated_at': now(), 'message': '已创建项目',
         'files': [], 'template': None, 'rules': None, 'references': None,
         'rules_extra': '', 'references_manual': [],
         'mainline': None, 'outline': None, 'sections': {}, 'figures': [],
         'revisions': [], 'check_report': None, 'build': None,
         'active_job': None, 'jobs': [], 'artifacts': [], 'notes': []}
    save_project(app, p)
    return p


def update_project(app, pid, patch):
    p = get_project(app, pid)
    patch = patch if isinstance(patch, dict) else {}
    if 'name' in patch:
        name = str(patch.get('name', '')).strip()[:100]
        if not name:
            raise ValueError('请填写论文名称')
        p['name'] = name
    for key, allowed in (('paper_kind', ('research', 'modeling')), ('language', ('zh', 'en')), ('stage', STAGES)):
        if key in patch:
            if patch[key] not in allowed:
                raise ValueError('无效的项目设置：' + key)
            p[key] = patch[key]
    for key in ('venue', 'event', 'topic'):
        if key in patch:
            p[key] = str(patch[key])[:2000]
    return save_project(app, p)


# ---------------------------------------------------------------- file zones

def _recompute_zone(app, p, zone):
    if zone == 'template':
        p['template'] = template_check(app, p)
    elif zone == 'rules':
        p['rules'] = rules_checklist(app, p)
    elif zone == 'reference':
        p['references'] = references_registry(app, p)


def _advance_stage(app, p):
    if p['files'] and p['stage'] == 'scoping':
        p['stage'] = 'material'


def add_files(app, pid, zone, files):
    if zone not in ZONES:
        raise ValueError('上传区无效')
    p = get_project(app, pid)
    files = files if isinstance(files, list) else []
    if not files:
        raise ValueError('没有可上传的文件')
    if len(p['files']) + len(files) > MAX_FILES:
        raise ValueError('项目文件数超过上限 %d' % MAX_FILES)
    existing = {f['name'].casefold() for f in p['files']}
    validated = []
    for f in files:
        filename = str(f.get('name', ''))
        if '/' in filename or '\\' in filename or not filename or len(filename) > 180:
            raise ValueError('文件名无效：' + filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED:
            raise ValueError('不支持此文件类型：' + filename)
        if filename.casefold() in existing:
            raise ValueError('项目内文件名不能重复：' + filename)
        if filename.casefold() in RESERVED:
            raise ValueError('请更改与交付文件冲突的上传文件名：' + filename)
        try:
            content = base64.b64decode(f.get('content', ''), validate=True)
        except Exception:
            raise ValueError('文件编码无效：' + filename)
        if not content or len(content) > MAX_FILE:
            raise ValueError('文件为空或超过60MB：' + filename)
        existing.add(filename.casefold())
        validated.append((filename, suffix, content, f))
    total = sum(f['size'] for f in p['files']) + sum(len(c) for _, _, c, _ in validated)
    if total > MAX_BYTES:
        raise ValueError('项目文件总大小超过200MB')
    for filename, suffix, content, src in validated:
        fid = uuid.uuid4().hex
        (project_dir(app, pid) / (fid + suffix)).write_bytes(content)
        role = str(src.get('role') or _default_role(zone))
        if role not in PROJECT_ROLES:
            raise ValueError('材料角色无效')
        purpose = str(src.get('purpose', '')).strip()[:200]
        if zone == 'material' and not purpose:
            raise ValueError('研究材料需填写一句用途说明：' + filename)
        p['files'].append({'id': fid, 'name': filename, 'suffix': suffix, 'zone': zone, 'role': role,
                           'purpose': purpose, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
                           'added_at': now(), 'characters': None, 'pages': None, 'notes': [], 'tags': []})
    extract_inventory(app, p)
    _recompute_zone(app, p, zone)
    _advance_stage(app, p)
    save_project(app, p)
    return p


def delete_file(app, pid, file_id):
    p = get_project(app, pid)
    target = next((f for f in p['files'] if f['id'] == file_id), None)
    if not target:
        raise ValueError('文件不存在')
    p['files'] = [f for f in p['files'] if f['id'] != file_id]
    folder = project_dir(app, pid)
    for path in (folder / (file_id + target['suffix']), folder / 'txt' / (file_id + '.txt')):
        if path.exists():
            path.unlink()
    _recompute_zone(app, p, target['zone'])
    return save_project(app, p)


def extract_inventory(app, p):
    folder = project_dir(app, p['id']); (folder / 'txt').mkdir(exist_ok=True)
    for f in p['files']:
        if f['suffix'] in ('.png', '.jpg', '.jpeg', '.eps', '.zip'):
            f['characters'] = 0
            if not f.get('notes'):
                f['notes'] = ['二进制或打包资源，未解析文本']
            continue
        try:
            text, notes, pages = app.extract(folder / (f['id'] + f['suffix']), f['suffix'])
        except Exception as exc:
            f['characters'] = 0; f['notes'] = ['解析失败：' + str(exc)[:120]]
            continue
        f['characters'] = len(text); f['pages'] = pages; f['notes'] = notes
        if text.strip():
            (folder / 'txt' / (f['id'] + '.txt')).write_text(text, encoding='utf-8')
    return p


def _file_text(app, p, f):
    path = project_dir(app, p['id']) / 'txt' / (f['id'] + '.txt')
    return path.read_text(encoding='utf-8') if path.exists() else ''


# ---------------------------------------------------------------- template check

def read_zip_entries(path, max_entries=400, max_entry=4 * 1024 * 1024, max_total=40 * 1024 * 1024):
    """Read a template ZIP into memory with zip-slip and size-bomb guards."""
    out = {}; total = 0
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > max_entries:
            raise ValueError('模板 ZIP 条目过多（>%d）' % max_entries)
        for info in infos:
            name = info.filename
            if name.endswith('/'):
                continue
            if name.startswith('/') or '\\' in name or any(part in ('..', '') for part in name.split('/')):
                raise ValueError('ZIP 包含非法或穿越路径：' + name)
            if info.file_size > max_entry:
                raise ValueError('ZIP 内单个文件过大：' + name)
            total += info.file_size
            if total > max_total:
                raise ValueError('ZIP 解压体积过大（>40MB）')
            out[name] = z.read(info)
    return out


def _main_tex_candidates(entries):
    """entries: {name: text}. Return names that look like a compilable main file."""
    out = []
    for name, text in entries.items():
        if not name.lower().endswith('.tex'):
            continue
        if 'PINKPIG_BODY_START' in text or 'MATHM_BODY_START' in text:
            out.append(name)
        elif r'\documentclass' in text and r'\begin{document}' in text:
            out.append(name)
    return out


def template_check(app, p, file_id=None, main=None):
    files = [f for f in p['files'] if f['zone'] == 'template']
    if not files:
        return None
    tf = next((f for f in files if f['id'] == file_id), None) or files[-1]
    folder = project_dir(app, p['id']); path = folder / (tf['id'] + tf['suffix'])
    kind = tf['suffix'].lstrip('.')
    t = {'file_id': tf['id'], 'name': tf['name'], 'kind': kind, 'entries': [], 'candidates': [], 'main': None,
         'bib_files': [], 'cls_files': [], 'sty_files': [], 'bst_files': [], 'image_files': [],
         'markers': {'start': False, 'end': False, 'count': [0, 0]},
         'writable_region': {'kind': 'none', 'confident': False},
         'cover': {'found': False, 'excerpt': ''}, 'engine_hint': 'unknown',
         'fonts': {'declared': [], 'local_available': [], 'missing': []}, 'issues': [], 'checked_at': now()}
    def issue(sev, msg):
        t['issues'].append({'severity': sev, 'message': msg})
    if kind == 'zip':
        entries = read_zip_entries(path)
        t['entries'] = [{'name': n, 'size': len(b), 'suffix': Path(n).suffix.lower()} for n, b in sorted(entries.items())]
        texts = {n: b.decode('utf-8-sig', 'replace') for n, b in entries.items() if n.lower().endswith('.tex')}
        t['candidates'] = _main_tex_candidates(texts)
        t['bib_files'] = [n for n in entries if n.lower().endswith('.bib')]
        t['cls_files'] = [n for n in entries if n.lower().endswith('.cls')]
        t['sty_files'] = [n for n in entries if n.lower().endswith('.sty')]
        t['bst_files'] = [n for n in entries if n.lower().endswith('.bst')]
        t['image_files'] = [n for n in entries if Path(n).suffix.lower() in ('.png', '.jpg', '.jpeg', '.eps', '.pdf')]
        if len(t['candidates']) == 1:
            t['main'] = t['candidates'][0]
        elif len(t['candidates']) > 1:
            t['main'] = main if main in t['candidates'] else None
            issue('must', '检测到多个候选主文件，请在“模板检查”中指定主 .tex。')
        else:
            issue('must', '未在 ZIP 中找到可编译的主 .tex（需含 \\documentclass 与 \\begin{document}）。')
        names = set(entries)
        text = texts.get(t['main'], '') if t['main'] else '\n'.join(texts.values())
        for ref in re.findall(r'\\(?:input|include|bibliography|addbibresource)\{([^}]+)\}', text):
            base = ref if Path(ref).suffix else ref + '.tex'
            if base not in names and not any(n.startswith(ref) for n in names):
                issue('must', '模板引用的文件不在 ZIP 中：' + ref)
    elif kind == 'tex':
        text = path.read_text(encoding='utf-8-sig', errors='replace')
        t['entries'] = [{'name': tf['name'], 'size': len(text.encode()), 'suffix': '.tex'}]
        t['candidates'] = _main_tex_candidates({tf['name']: text})
        t['main'] = t['candidates'][0] if t['candidates'] else None
        if not t['main']:
            issue('must', '该 .tex 未包含 \\documentclass/\\begin{document}。')
        issue('verify', '单独上传 .tex 时，请确认其引用的 .cls/.sty/文献与图片已一并上传。')
    else:
        issue('verify', 'Word/PDF 仅作结构与版式参考，不能直接作为可编译 LaTeX 模板；如需对应模板请上传 .tex 或 LaTeX 项目 ZIP。')
        t['writable_region'] = {'kind': 'none', 'confident': False}
        return t
    markers_start = text.count('PINKPIG_BODY_START') + text.count('MATHM_BODY_START')
    markers_end = text.count('PINKPIG_BODY_END') + text.count('MATHM_BODY_END')
    t['markers'] = {'start': markers_start > 0, 'end': markers_end > 0, 'count': [markers_start, markers_end]}
    import writing
    try:
        writing.template_parts(text)
        t['writable_region'] = {'kind': 'markers', 'confident': True}
    except ValueError:
        if r'\begin{document}' in text and r'\end{document}' in text:
            t['writable_region'] = {'kind': 'document-env', 'confident': False}
            issue('must', '模板未标注可写区间（% PINKPIG_BODY_START/END）；正式生成前需人工确认，或改用示例模板。')
        else:
            issue('must', '模板缺少可写区间，也无法定位 document 环境。')
    begin = text.find(r'\begin{document}')
    marker = text.find('% PINKPIG_BODY_START')
    if marker < 0:
        marker = text.find('% MATHM_BODY_START')
    if begin >= 0 and marker > begin:
        excerpt = text[begin:marker]
        t['cover'] = {'found': excerpt.strip() != r'\begin{document}', 'excerpt': excerpt[-800:]}
    t['engine_hint'] = 'xelatex' if re.search(r'fontspec|xeCJK|ctex|setmainfont|setCJKmainfont|cumcmthesis', text) else 'pdflatex'
    declared = sorted(set(re.findall(r'\\(?:setmainfont|setCJKmainfont|setCJKfamilyfont)\{([^}]+)\}', text)))
    import typography
    known = set(typography.LATIN) | set(typography.CJK) | {'inherit'}
    t['fonts'] = {'declared': declared, 'local_available': [f for f in declared if f in known], 'missing': [f for f in declared if f not in known]}
    if t['fonts']['missing']:
        issue('verify', '模板声明了本应用字体白名单之外的字体：' + '、'.join(t['fonts']['missing']) + '（需在本机 LaTeX 环境确认可用）。')
    return t


# ---------------------------------------------------------------- rules / references

_RULE_GROUPS = [('篇幅与页数', ['页', '字数', '篇幅']), ('字号与字体', ['字号', '字体', '宋体', 'Times', '黑体', '小四', '五号']),
                ('页面设置', ['页边距', '行距', '纸张', 'A4']), ('匿名与标识', ['匿名', '不得出现', '学校', '姓名']),
                ('摘要与关键词', ['摘要', '关键词']), ('参考文献', ['参考文献', '引用', '著录']), ('图表与公式', ['图表', '图题', '表题', '公式', '编号'])]


def rules_checklist(app, p):
    folder = project_dir(app, p['id'])
    rules_files = [f for f in p['files'] if f['zone'] == 'rules']
    texts = [_file_text(app, p, f) for f in rules_files]
    rules_text = '\n'.join(texts)
    extra = str(p.get('rules_extra', ''))[:4000]
    items = []
    for name, words in _RULE_GROUPS:
        hits = [w for w in words if w in rules_text]
        items.append({'group': name, 'requirement': ('规范中检出关键词：' + '、'.join(hits)) if hits else '规范中未检出相关关键词，需人工确认',
                      'source': 'file' if rules_text.strip() else 'missing', 'verified': 'unverified', 'evidence': ''})
    if extra:
        items.append({'group': '用户补充要求', 'requirement': extra[:400], 'source': 'extra', 'verified': 'unverified', 'evidence': ''})
    conflicts = []
    tmpl = p.get('template')
    if tmpl:
        declared = (tmpl.get('fonts') or {}).get('declared') or []
        if declared and any(w in (rules_text + extra) for w in ('字体', '宋体', 'Times', '黑体')):
            conflicts.append({'item': '字体', 'template': '模板声明字体：' + ('、'.join(declared) or '（未声明）'),
                              'rules': '规范/补充要求涉及字体', 'impact': '可能与模板冲突',
                              'suggestion': '不覆盖模板；在正文或检查说明中标注待人工核验。'})
        if (tmpl.get('cover') or {}).get('found') and '匿名' in (rules_text + extra):
            conflicts.append({'item': '匿名/封面', 'template': '模板含封面/声明固定内容', 'rules': '规范要求匿名',
                              'impact': '模板封面可能含身份信息', 'suggestion': '不覆盖模板；导出前人工检查并清除身份信息。'})
    if not rules_text.strip() and not extra:
        conflicts = conflicts
    truncated = len(rules_text) > 120000
    return {'file_ids': [f['id'] for f in rules_files], 'extra': extra, 'rules_text_chars': len(rules_text),
            'truncated': truncated, 'items': items, 'conflicts': conflicts, 'built_at': now()}


def references_registry(app, p):
    folder = project_dir(app, p['id'])
    bib_files = [f for f in p['files'] if f['zone'] == 'reference' and f['suffix'] == '.bib']
    entries = []; counts = {}
    for f in bib_files:
        text = (folder / (f['id'] + '.bib')).read_text(encoding='utf-8-sig', errors='replace')
        for k, t in re.findall(r'@(\w+)\s*\{\s*([^,\s]+)', text):
            entries.append({'key': t, 'type': k, 'title': '', 'year': '', 'source': 'bib', 'verified': True, 'note': f['name']})
            counts[t] = counts.get(t, 0) + 1
    for m in (p.get('references_manual') or []):
        m = str(m)[:200]
        entries.append({'key': '', 'type': '', 'title': m, 'year': '', 'source': 'manual', 'verified': False, 'note': '手工条目，来源待补充'})
    import review
    body = review.full_body(p)
    texts = [body]
    for f in p['files']:
        if f['suffix'] not in ('.png', '.jpg', '.jpeg', '.eps', '.zip'):
            texts.append(_file_text(app, p, f))
    cited = {k.strip() for text in texts for keys in re.findall(r'\\cite\w*\*?(?:\[[^\]]*\])*\{([^}]+)\}', text) for k in keys.split(',')}
    provided = set(counts)
    missing = [{'key': k, 'why': '正文引用了未提供的键'} for k in sorted(cited - provided)]
    return {'bib_file_ids': [f['id'] for f in bib_files], 'entries': entries, 'missing': missing,
            'stats': {'count': len(counts), 'duplicates': sorted(k for k, c in counts.items() if c > 1)}, 'built_at': now()}


# ---------------------------------------------------------------- job framework

def _job_fetch(app, pid):
    def fetch(_=None):
        p = get_project(app, pid)
        return p.get('active_job') or {'cancel_requested': False}
    return fetch


def _job_save(app, pid):
    def save_fn(job):
        p = get_project(app, pid)
        p['active_job'] = job
        save_project(app, p)
    return save_fn


def start_job(app, p, kind, target=None, payload=None):
    if kind not in JOB_KINDS:
        raise ValueError('作业类型无效')
    job = {'id': uuid.uuid4().hex, 'kind': kind, 'target': target, 'status': 'queued', 'progress': 0,
           'message': '等待处理', 'steps': [{'name': n, 'status': 'pending'} for n in JOB_STEPS[kind]],
           'events': [], 'cancel_requested': False, 'notes': []}
    p['active_job'] = job
    save_project(app, p)
    app.POOL.submit(run_job, app, p['id'], job['id'], kind, target, payload or {})
    return job


def run_job(app, pid, job_id, kind, target, payload):
    p = get_project(app, pid)
    job = p.get('active_job')
    if not job or job['id'] != job_id:
        return
    fetch = _job_fetch(app, pid); save_fn = _job_save(app, pid)
    job.update(status='running', message='开始处理'); save_fn(job)
    try:
        {'mainline': build_mainline, 'outline': build_outline, 'section': write_section,
         'polish': polish, 'check': run_check, 'build': build_export}[kind](app, p, job, payload, fetch, save_fn)
        p = get_project(app, pid)
        p['active_job'].update(status='completed', progress=100, message='完成')
        save_project(app, p)
    except InterruptedError as exc:
        p = get_project(app, pid)
        p['active_job'].update(status='cancelled', message=str(exc))
        save_project(app, p)
    except Exception as exc:
        p = get_project(app, pid); job = p['active_job']; job['status'] = 'failed'
        for s in job['steps']:
            if s['status'] == 'running':
                s['status'] = 'failed'
        job['message'] = str(exc)[:300] if isinstance(exc, (ValueError, UnicodeError)) else '处理失败：' + type(exc).__name__
        save_project(app, p)


# ---------------------------------------------------------------- AI helpers

def parse_json_block(raw):
    text = (raw or '').strip()
    fenced = re.findall(r'```(?:json)?\s*\n(.*?)```', text, re.S)
    cand = max(fenced, key=len) if fenced else text
    m = re.search(r'(\{.*\}|\[.*\])', cand, re.S)
    if m:
        try:
            return json.loads(m.group(1)), True
        except ValueError:
            pass
    return None, False


_MAT_ORDER = {'rules': 0, 'problem': 1, 'paper': 2, 'reference': 3, 'support': 4, 'template': 5}


def gather_materials(app, p, roles=None, budget=120000):
    segs = []; notes = []; left = budget; truncated = False
    for f in sorted(p['files'], key=lambda f: _MAT_ORDER.get(f['role'], 9)):
        if f['suffix'] in ('.png', '.jpg', '.jpeg', '.eps', '.zip'):
            continue
        if roles and f['role'] not in roles:
            continue
        text = _file_text(app, p, f)
        if not text.strip():
            continue
        allowed = min(len(text), max(0, left)); left -= allowed
        if allowed < len(text):
            truncated = True
        segs.append(f'\n<材料 文件={json.dumps(f["name"], ensure_ascii=False)} 角色={f["role"]} 用途={json.dumps(f.get("purpose",""), ensure_ascii=False)}>\n{text[:allowed]}\n</材料>')
    if truncated:
        notes.append('本次输入因长度预算截断，不能视为全文分析。')
    return '\n'.join(segs), {'truncated': truncated, 'notes': notes}


def context_for_section(app, p, sid):
    import outline
    items = (p.get('outline') or {}).get('items') or []
    idx = next((i for i, it in enumerate(items) if it['sid'] == sid), None)
    parts = ['<只读上下文>', '研究主线：', outline.mainline_text(p.get('mainline'))]
    if idx is not None:
        if idx > 0:
            prev = items[idx - 1]; sec = (p.get('sections') or {}).get(prev['sid']) or {}
            parts.append(f"上一节《{prev['title']}》要点：{prev.get('question','')}；结尾：{(sec.get('body_latex') or '')[-200:]}")
        if idx + 1 < len(items):
            nxt = items[idx + 1]
            parts.append(f"下一节《{nxt['title']}》将回答：{nxt.get('question','')}")
    parts.append('</只读上下文>')
    return '\n'.join(parts)


def prompt_mainline(p):
    return ('你是研究主线的整理者，不是论文写作者，不产出正文。只依据 <材料> 中的真实内容整理主线。'
            '每条结论必须给出 file_id 与原文短引；找不到证据的放入 missing_evidence，绝不编造。'
            '固定术语与符号，输出 terms（term/definition/unit），后续章节必须复用。'
            '结论必须写 bounds（适用边界）；越界推断标 source:"unverified"。'
            '只输出唯一 JSON，键名逐字如下：'
            '{"question":"","method":"","assumptions":[""],"terms":[{"term":"","definition":"","unit":""}],'
            '"results":[{"claim":"","evidence":[{"file_id":"","quote":""}],"source":"real|unverified"}],"bounds":"","missing_evidence":[""]}。'
            '不要输出解释、Markdown 表格或额外键。')


def prompt_outline(p):
    return ('你根据研究主线生成全文提纲。每节必须含 title/question/uses_materials/uses_figures/missing_evidence；'
            'uses_materials 只能用提供的 file_id；不得编造材料或文献。'
            '分别输出 reading_order（读者阅读顺序）与 writing_order（建议写作顺序，方法/结果先行），两者必须是同一组 sid 的不同排列。'
            '只输出唯一 JSON：{"items":[{"title":"","question":"","anchor":"","level":1,"uses_materials":[],"uses_figures":[],"missing_evidence":[]}],'
            '"reading_order":[],"writing_order":[]}。sid 将本地生成，你只需给出标题等。')


def prompt_section(p, it, instruction):
    return ('你为“论文项目”的单个章节生成**待采纳草稿**，采纳前不并入论文，也不得改动其他章节。'
            '必须复用主线中的术语与符号。本节要回答：' + str(it.get('question', '')) + '。'
            '相关材料见 <材料>；材料不支持的数值或结论一律写“待补充”。'
            '只写选定章节，只返回纯 LaTeX（不含代码围栏、说明或文档外壳）；不得新增参考文献键或引用未提供的图片。'
            '用户补充要求：' + instruction)


def prompt_polish(p, target, kind, instruction):
    return ('你对选中范围做润色，**只改选中范围，范围外一字不改**；参考全文仅用于判断衔接与一致性，不得写入输出。'
            f'润色类型：{kind}。'
            '保留事实、数值、单位、符号、\\cite 键、\\label 与 LaTeX 结构；不扩写研究结论，不新增数据。'
            '输出唯一 JSON：{"items":[{"original":"","suggestion":"","reason":""}],'
            '"related":[{"sid":"","proposed_change":"","reason":""}]}；related 仅报告跨章节一致性问题，不得替换其他章节内容。'
            + ('用户补充要求：' + instruction if instruction else ''))


def prompt_check(p, scope):
    return ('你对论文做语义一致性检查（格式要求完成情况由本地确定性检查给出，不要重复）。'
            '逐条检查：研究问题↔结论对应；摘要/结果/讨论/结论一致；方法口径/数据口径/符号/单位冲突；'
            '图表引用与参考文献对应；重复论述、缺失过渡、待补充内容。'
            '每项必须 severity ∈ must|should|verify，且 location.quote 必须是正文中可字面检索的片段；无法定位时必须 severity=verify 并在 message 说明“未能定位到正文”。'
            '不得编造未提供的事实、数值或文献；引用只核验“是否对应”，不核验文献真实性。'
            '只输出 JSON 数组：[{"category":"","severity":"must","location":{"sid":"","quote":""},"message":"","suggestion":""}]。')


def _guidance(app, o_kwargs):
    import studio
    o = studio.options({'writing_options': o_kwargs})
    routed, loaded = studio.guidance(app.SKILLS, o)
    return o, routed, loaded


def build_mainline(app, p, job, payload, fetch, save_fn):
    import outline
    app.checkpoint(job, 0, fetch=fetch, save_fn=save_fn)
    materials, meta = gather_materials(app, p)
    app.event(job, '已收集材料，正在整理研究主线', save_fn)
    app.checkpoint(job, 0, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 1, fetch=fetch, save_fn=save_fn)
    _, routed, _ = _guidance(app, {'mode': 'full', 'paper_kind': p['paper_kind'], 'language': p['language']})
    raw = app.model_call(app.WRITING_SKILL, materials, p['name'], '', system=prompt_mainline(p) + '\n\n' + routed,
                         max_tokens=int(app.env('MAINLINE_MAX_TOKENS', '6000')))
    data, structured = parse_json_block(raw)
    if structured and isinstance(data, dict):
        mainline = {'question': str(data.get('question', ''))[:1000], 'method': str(data.get('method', ''))[:4000],
                    'assumptions': [str(x)[:300] for x in (data.get('assumptions') or [])][:20],
                    'terms': [{'term': str(t.get('term', ''))[:60], 'definition': str(t.get('definition', ''))[:300], 'unit': str(t.get('unit', ''))[:40]}
                              for t in (data.get('terms') or []) if isinstance(t, dict)][:60],
                    'results': [{'claim': str(r.get('claim', ''))[:500], 'evidence': r.get('evidence') or [],
                                 'source': 'real' if r.get('source') == 'real' else 'unverified'}
                                for r in (data.get('results') or []) if isinstance(r, dict)][:40],
                    'bounds': str(data.get('bounds', ''))[:1000],
                    'missing_evidence': [str(x)[:200] for x in (data.get('missing_evidence') or [])][:30],
                    'source': 'ai', 'updated_at': now(), 'notes': meta['notes']}
    else:
        mainline = {'question': '', 'method': '', 'assumptions': [], 'terms': [], 'results': [], 'bounds': '',
                    'missing_evidence': [], 'source': 'ai', 'structured': False, 'raw': raw[:8000],
                    'updated_at': now(), 'notes': meta['notes'] + ['模型返回未结构化，需人工阅读原文。']}
    mainline['missing_evidence'] += [g for g in outline.mainline_gaps(mainline) if g not in mainline['missing_evidence']]
    p['mainline'] = mainline
    if p['stage'] in ('scoping', 'material'):
        p['stage'] = 'mainline'
    app.checkpoint(job, 1, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 2, fetch=fetch, save_fn=save_fn)
    app.event(job, '研究主线已保存', save_fn)
    app.checkpoint(job, 2, 'done', fetch=fetch, save_fn=save_fn)
    save_project(app, p)


def build_outline(app, p, job, payload, fetch, save_fn):
    import outline
    app.checkpoint(job, 0, fetch=fetch, save_fn=save_fn)
    materials, meta = gather_materials(app, p)
    base = outline.mainline_text(p.get('mainline'))
    app.checkpoint(job, 0, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 1, fetch=fetch, save_fn=save_fn)
    _, routed, _ = _guidance(app, {'mode': 'full', 'paper_kind': p['paper_kind'], 'language': p['language']})
    raw = app.model_call(app.WRITING_SKILL, '\n'.join(['研究主线：', base, materials]), p['name'], '',
                         system=prompt_outline(p) + '\n\n' + routed, max_tokens=int(app.env('OUTLINE_MAX_TOKENS', '6000')))
    data, structured = parse_json_block(raw)
    if structured and isinstance(data, dict):
        raw_items = [{k: v for k, v in it.items() if k != 'sid'} for it in (data.get('items') or []) if isinstance(it, dict)]
        items = outline.normalize_items(raw_items, p['paper_kind'])
    else:
        items = []
    if not items:
        items = outline.normalize_items([], p['paper_kind'])
    reading = [s for s in (data.get('reading_order') if isinstance(data, dict) else []) or [] if s in {it['sid'] for it in items}]
    if set(reading) != {it['sid'] for it in items}:
        reading = outline.reading_order(items)
    o = {'items': items, 'reading_order': reading, 'writing_order': outline.writing_order(items),
         'source': 'ai', 'structured': bool(structured and items), 'updated_at': now(), 'notes': meta['notes']}
    p['outline'] = o
    if p['stage'] in ('scoping', 'material', 'mainline'):
        p['stage'] = 'outline'
    app.checkpoint(job, 1, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 2, fetch=fetch, save_fn=save_fn)
    app.event(job, '全文提纲已保存', save_fn)
    app.checkpoint(job, 2, 'done', fetch=fetch, save_fn=save_fn)
    save_project(app, p)


# ---------------------------------------------------------------- section writing

def _image_names(p):
    names = set()
    for f in p['files']:
        if f['suffix'] in ('.png', '.jpg', '.jpeg', '.eps'):
            names.add(f['name'])
    for f in p['figures']:
        for path in (f.get('assets') or {}).values():
            names.add(Path(path).name)
        names.add(Path(f.get('assets', {}).get('pdf', '') or '').stem)
    return names


def _bibkeys(p):
    return {e['key'] for e in ((p.get('references') or {}).get('entries') or []) if e.get('key')}


def write_section(app, p, job, payload, fetch, save_fn):
    import writing
    sid = str(payload.get('sid') or job.get('target') or '')
    items = (p.get('outline') or {}).get('items') or []
    it = next((x for x in items if x['sid'] == sid), None)
    if not it:
        raise ValueError('章节不存在，请先生成或保存提纲')
    app.checkpoint(job, 0, fetch=fetch, save_fn=save_fn)
    ctx = context_for_section(app, p, sid)
    materials, meta = gather_materials(app, p)
    instruction = str(payload.get('instruction') or '')[:2000]
    constraints = ('本节为待采纳草稿，采纳前不并入论文，也不得改动其他章节；必须复用研究主线中的术语与符号；'
                   '本节要回答：' + str(it.get('question', '')) + '；材料不支持的数值或结论一律写“待补充”；'
                   '不得新增参考文献键，不得引用未提供的图片。')
    app.checkpoint(job, 0, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 1, fetch=fetch, save_fn=save_fn)
    o = {'mode': 'section', 'section': it.get('anchor') or 'method', 'paper_kind': p['paper_kind'],
         'language': p['language'], 'action': 'draft', 'instructions': (instruction + ' ' + constraints)[:4000]}
    raw = app.model_call(app.WRITING_SKILL, '\n'.join([ctx, materials]), p['name'], '', writing_options=o)
    body = writing.extract_body(raw)
    app.checkpoint(job, 1, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 2, fetch=fetch, save_fn=save_fn)
    folder = project_dir(app, p['id'])
    writing.validate_body(body, folder, images=_image_names(p), bibkeys=_bibkeys(p))
    sec = p['sections'].get(sid) or {'sid': sid, 'title': it['title'], 'versions': []}
    if sec.get('body_latex'):
        sec.setdefault('versions', []).append({'id': 'v%d' % (len(sec['versions']) + 1), 'body': sec['body_latex'],
                                               'reason': '生成前', 'created_at': now()})
    sec.update({'title': it['title'], 'body_latex': body, 'status': 'draft', 'source': 'ai',
                'instruction': instruction, 'updated_at': now(), 'notes': meta['notes']})
    p['sections'][sid] = sec
    if p['stage'] in ('scoping', 'material', 'mainline', 'outline'):
        p['stage'] = 'drafting'
    app.event(job, '本节草稿已生成（待采纳）', save_fn)
    app.checkpoint(job, 2, 'done', fetch=fetch, save_fn=save_fn)
    save_project(app, p)


def apply_decision(app, p, sid, payload):
    """draft actions on a section: adopt / reject / update / restore / delete."""
    action = payload.get('action', 'update')
    sec = p['sections'].get(sid)
    if not sec:
        if action not in ('update', 'adopt'):
            raise ValueError('章节不存在')
        items = (p.get('outline') or {}).get('items') or []
        title = next((it['title'] for it in items if it['sid'] == sid), sid)
        sec = {'sid': sid, 'title': title, 'body_latex': '', 'status': 'empty', 'versions': []}
        p['sections'][sid] = sec
    if action == 'adopt':
        if not (sec.get('body_latex') or '').strip():
            raise ValueError('本节还没有草稿可采纳')
        sec['status'] = 'adopted'; sec['updated_at'] = now()
    elif action == 'reject':
        sec['status'] = 'empty' if not sec.get('versions') else 'adopted'
        if not sec.get('versions'):
            sec['body_latex'] = ''
        sec['updated_at'] = now()
    elif action == 'update':
        sec['body_latex'] = str(payload.get('body', ''))[:200000]
        sec['status'] = 'draft' if sec.get('body_latex') else 'empty'
        sec['updated_at'] = now()
    elif action == 'restore':
        vid = payload.get('version_id')
        ver = next((v for v in sec.get('versions', []) if v['id'] == vid), None)
        if not ver:
            raise ValueError('版本不存在')
        if sec.get('body_latex'):
            sec['versions'].append({'id': 'v%d' % (len(sec['versions']) + 1), 'body': sec['body_latex'],
                                    'reason': '撤销前', 'created_at': now()})
        sec['body_latex'] = ver['body']; sec['status'] = 'draft'; sec['updated_at'] = now()
    elif action == 'delete':
        p['sections'].pop(sid, None)
    else:
        raise ValueError('无效的章节操作')
    return save_project(app, p)


# ---------------------------------------------------------------- polish

def polish(app, p, job, payload, fetch, save_fn):
    import outline
    target = payload.get('target') or {}
    sid = target.get('sid'); scope = target.get('scope', 'section'); pid = target.get('pid')
    kind = payload.get('kind', 'language'); instruction = str(payload.get('instruction') or '')[:2000]
    sec = (p.get('sections') or {}).get(sid)
    if not sec or not (sec.get('body_latex') or '').strip():
        raise ValueError('选中章节没有可润色的正文')
    body = sec['body_latex']
    if scope == 'paragraph':
        selection = outline.find_paragraph(body, pid)
        if selection is None:
            raise ValueError('选中的段落定位失败，请重新选择')
    else:
        selection = body
    items = (p.get('outline') or {}).get('items') or []
    it = next((x for x in items if x['sid'] == sid), None) or {'anchor': 'method'}
    app.checkpoint(job, 0, fetch=fetch, save_fn=save_fn)
    app.checkpoint(job, 0, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 1, fetch=fetch, save_fn=save_fn)
    o = {'mode': 'section', 'section': it.get('anchor') or 'method', 'paper_kind': p['paper_kind'],
         'language': p['language'], 'action': 'polish', 'instructions': instruction}
    raw = app.model_call(app.WRITING_SKILL, '\n'.join([context_for_section(app, p, sid), '<选中范围>', selection]),
                         p['name'], '', writing_options=o)
    data, structured = parse_json_block(raw)
    rev_items = []; related = []
    if structured and isinstance(data, dict):
        for x in (data.get('items') or []):
            if not isinstance(x, dict):
                continue
            rev_items.append({'iid': uuid.uuid4().hex[:12], 'original': str(x.get('original', ''))[:20000],
                              'suggestion': str(x.get('suggestion', ''))[:20000], 'reason': str(x.get('reason', ''))[:200],
                              'status': 'pending'})
        related = [{'sid': str(x.get('sid', ''))[:32], 'proposed_change': str(x.get('proposed_change', ''))[:400],
                    'reason': str(x.get('reason', ''))[:200]} for x in (data.get('related') or []) if isinstance(x, dict)]
    rev = {'rid': uuid.uuid4().hex[:12], 'target': {'scope': scope, 'sid': sid, 'pid': pid}, 'kind': kind,
           'instruction': instruction, 'status': 'open', 'structured': bool(structured and rev_items),
           'raw': raw[:8000], 'items': rev_items, 'related': related, 'created_at': now()}
    p['revisions'].append(rev)
    if p['stage'] in ('drafting', 'figures'):
        p['stage'] = 'polishing'
    app.checkpoint(job, 1, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 2, fetch=fetch, save_fn=save_fn)
    app.event(job, f'已生成 {len(rev_items)} 条润色对照', save_fn)
    app.checkpoint(job, 2, 'done', fetch=fetch, save_fn=save_fn)
    save_project(app, p)


def decide_revision(app, p, rid, payload):
    rev = next((r for r in p['revisions'] if r['rid'] == rid), None)
    if not rev:
        raise ValueError('润色记录不存在')
    action = payload.get('action', 'accept'); iid = payload.get('iid')
    sid = rev['target'].get('sid')
    sec = p['sections'].get(sid)
    if not sec:
        raise ValueError('章节不存在')
    targets = [i for i in rev['items'] if (iid in (None, 'all') or i['iid'] == iid) and i['status'] == 'pending']
    if not targets:
        raise ValueError('没有可处理的对照项')
    body = sec['body_latex']
    if action == 'accept':
        snapshot = body
        for item in targets:
            orig = item.get('original', '')
            if orig and orig in body:
                body = body.replace(orig, item.get('suggestion', ''), 1)
                item['status'] = 'accepted'
            else:
                item['status'] = 'rejected'
                item['reason'] = (item.get('reason') or '') + ' 定位失败，未应用（避免改错位置）。'
        if body != snapshot:
            sec.setdefault('versions', []).append({'id': 'v%d' % (len(sec['versions']) + 1), 'body': snapshot,
                                                   'reason': '润色前', 'created_at': now()})
            sec['body_latex'] = body; sec['status'] = 'draft'; sec['updated_at'] = now()
    else:
        for item in targets:
            item['status'] = 'rejected'
    rev['status'] = 'applied' if all(i['status'] != 'pending' for i in rev['items']) else 'partially_applied'
    return save_project(app, p)


# ---------------------------------------------------------------- full-text check

def run_check(app, p, job, payload, fetch, save_fn):
    import review
    scope = payload.get('scope') or {'kind': 'full'}
    use_ai = payload.get('use_ai', True)
    app.checkpoint(job, 0, fetch=fetch, save_fn=save_fn)
    det = review.deterministic_checks(p, scope)
    app.checkpoint(job, 0, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 1, fetch=fetch, save_fn=save_fn)
    ai_items = []; truncated = False; model_used = False
    if use_ai and app.env('API_KEY'):
        body = review.full_body(p)
        materials, meta = gather_materials(app, p, roles=('rules', 'problem', 'paper', 'support'), budget=120000)
        out, _ = parse_json_block(app.model_call(app.WRITING_SKILL, '\n'.join(['正文：', body, materials]), p['name'], '',
                                                system=prompt_check(p, scope), max_tokens=int(app.env('CHECK_MAX_TOKENS', '6000'))))
        truncated = meta['truncated']; model_used = True
        for x in (out or []):
            if not isinstance(x, dict):
                continue
            loc = x.get('location') or {}
            quote = str(loc.get('quote', '') if isinstance(loc, dict) else '')
            locatable = bool(quote) and quote in body
            ai_items.append({'id': uuid.uuid4().hex[:12], 'category': str(x.get('category', ''))[:60],
                             'severity': 'verify' if not locatable else (x.get('severity') if x.get('severity') in ('must', 'should', 'verify') else 'verify'),
                             'source': 'ai', 'location': {'sid': loc.get('sid'), 'quote': quote[:80]},
                             'message': str(x.get('message', ''))[:500] + ('' if locatable else '（未能定位到正文）'),
                             'evidence': '', 'suggestion': str(x.get('suggestion', ''))[:300], 'related': []})
    merged = review.merge(ai_items, det)
    report = {'run_at': now(), 'scope': scope, 'model_used': model_used, 'truncated': truncated,
              'items': merged, 'summary': review.summary(merged),
              'unverified': [i['message'][:120] for i in merged if i.get('severity') == 'verify'][:30]}
    p['check_report'] = report
    if p['stage'] in ('drafting', 'figures', 'polishing'):
        p['stage'] = 'checking'
    app.checkpoint(job, 1, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 2, fetch=fetch, save_fn=save_fn)
    app.event(job, f"检查完成：必须处理 {report['summary']['must']} / 建议 {report['summary']['should']} / 待核验 {report['summary']['verify']}", save_fn)
    app.checkpoint(job, 2, 'done', fetch=fetch, save_fn=save_fn)
    save_project(app, p)


# ---------------------------------------------------------------- figures

def _renumber(app, p):
    import outline
    num = outline.figure_numbering(p['figures'], (p.get('outline') or {}).get('items') or [])
    for f in p['figures']:
        f['number'] = num['tables' if f['kind'] == 'table' else 'figures'].get(f['fid'], 0)


def insert_figure(app, p, payload):
    import assets, os
    action = payload.get('action', 'add')
    if action == 'delete':
        p['figures'] = [f for f in p['figures'] if f['fid'] != payload.get('fid')]
        _renumber(app, p); return save_project(app, p)
    fid = str(payload.get('fid') or ('fig' + uuid.uuid4().hex[:8]))
    kind = payload.get('kind', 'generated')
    f = {'fid': fid, 'kind': 'table' if payload.get('as_table') else kind, 'table': bool(payload.get('as_table')),
         'label': str(payload.get('label') or ('tab:' + fid if payload.get('as_table') else 'fig:' + fid))[:60],
         'caption': str(payload.get('caption') or '')[:600], 'citing_sections': payload.get('citing_sections') or [],
         'created_at': now()}
    folder = project_dir(app, p['id']); fdir = folder / 'figures' / fid; fdir.mkdir(parents=True, exist_ok=True)
    if kind == 'generated':
        src = next((x for x in p['files'] if x['id'] == payload.get('source_file_id')), None)
        if not src or src['suffix'] != '.csv':
            raise ValueError('生成图表需要选择一份 CSV 数据')
        headers, rows = assets.read_csv(folder / (src['id'] + '.csv'))
        o = {'mode': 'figure', 'chart_type': payload.get('chart_type', 'line'), 'x_column': payload.get('x_column', ''),
             'y_columns': payload.get('y_columns', ''), 'x_label': payload.get('x_label', ''), 'y_label': payload.get('y_label', ''),
             'font_latin': 'inherit', 'font_cjk': 'inherit', 'font_size': 'inherit', 'instructions': ''}
        settings = assets.chart_settings(headers, rows, o)
        (fdir / 'settings.json').write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8')
        shutil.copy2(Path(assets.__file__).with_name('figure_renderer.py'), fdir / 'plot.py')
        shutil.copy2(folder / (src['id'] + '.csv'), fdir / 'source-data.csv')
        env = os.environ.copy(); env['MPLCONFIGDIR'] = str(fdir / 'mpl'); env['MPLBACKEND'] = 'Agg'
        proc = subprocess.run([sys.executable, '-B', str(fdir / 'plot.py')], cwd=fdir, env=env, capture_output=True, text=True, timeout=90)
        if proc.returncode:
            raise ValueError('本地绘图失败：' + (proc.stderr or '')[-300:])
        f['source_file_id'] = src['id']
        f['assets'] = {'png': f'figures/{fid}/figure.png', 'pdf': f'figures/{fid}/figure.pdf', 'svg': f'figures/{fid}/figure.svg'}
        f['provenance'] = {'csv': f'figures/{fid}/source-data.csv', 'script': f'figures/{fid}/plot.py'}
    elif kind == 'uploaded':
        try:
            content = base64.b64decode(payload.get('content', ''), validate=True)
        except Exception:
            raise ValueError('图片编码无效')
        ext = Path(str(payload.get('name') or 'figure.png')).suffix.lower()
        if ext not in ('.png', '.jpg', '.jpeg', '.eps'):
            raise ValueError('仅支持 PNG/JPG/EPS 图片')
        (fdir / ('figure' + ext)).write_bytes(content)
        f['assets'] = {'image': f'figures/{fid}/figure{ext}'}
    else:
        raise ValueError('未知图表类型')
    p['figures'] = [x for x in p['figures'] if x['fid'] != fid] + [f]
    _renumber(app, p)
    if p['stage'] in ('drafting', 'outline'):
        p['stage'] = 'figures'
    return save_project(app, p)


# ---------------------------------------------------------------- source & export

def render_source(app, p):
    """Assemble main tex from the template (or a default shell) + adopted sections."""
    import writing
    items = (p.get('outline') or {}).get('items') or []
    parts = []
    for it in items:
        sec = (p.get('sections') or {}).get(it['sid']) or {}
        title = it['title'].replace('}', '').replace('{', '')
        body = sec.get('body_latex') or ''
        parts.append('\\section{' + title + '}\n' + body)
    body = '\n\n'.join(parts) if parts else '% 尚无正文\n'
    folder = project_dir(app, p['id']); scratch = folder / 'scratch'; project = scratch / 'project'
    if scratch.exists():
        shutil.rmtree(scratch)
    project.mkdir(parents=True)
    tf = next((f for f in p['files'] if f['zone'] == 'template'), None)
    template = None; main_name = 'main.tex'; note = None
    tmpl_info = p.get('template') or {}
    if tf and tmpl_info.get('main'):
        if tf['suffix'] == '.zip':
            entries = read_zip_entries(folder / (tf['id'] + '.zip'))
            for name, data in entries.items():
                (project / name).write_bytes(data)
            main_name = tmpl_info['main']
            template = (project / main_name).read_text(encoding='utf-8-sig', errors='replace')
        else:
            template = (folder / (tf['id'] + '.tex')).read_text(encoding='utf-8-sig', errors='replace')
            main_name = tf['name']
            (project / main_name).write_text(template, encoding='utf-8')
        note = '仅替换模板的 PINKPIG_BODY_START/END 区间；导言区与封面保持原文。'
    if template is None:
        use_cumcm = p['paper_kind'] == 'modeling' and p['language'] == 'zh'
        cumcm = app.SKILLS / 'math-modeling-skill/templates/cumcmthesis/cumcmthesis.cls'
        if use_cumcm and cumcm.exists():
            shutil.copy2(cumcm, project / 'cumcmthesis.cls')
            template = (r'\documentclass[withoutpreface,bwprint]{cumcmthesis}' + '\n'
                        + r'% 该类内部加载 ctex 提供中文支持' + '\n' + r'\usepackage{mathtools}' + '\n'
                        + writing.SHIMS + '\n' + r'\begin{document}' + '\n' + writing.START + '\n' + writing.END + '\n' + r'\end{document}' + '\n')
            note = '数模中文默认套用国赛 cumcmthesis 模板（需 XeLaTeX）。'
        else:
            cls = r'\documentclass[UTF8,a4paper,12pt]{ctexart}' if p['language'] == 'zh' else r'\documentclass[a4paper,12pt]{article}'
            template = cls + '\n' + writing.PACKAGES + '\n' + writing.SHIMS + '\n' + r'\begin{document}' + '\n' + writing.START + '\n' + writing.END + '\n' + r'\end{document}' + '\n'
            note = '未使用自定义模板，采用通用外壳。'
        main_name = 'main.tex'
    pre, old, post = writing.template_parts(template)
    (project / main_name).write_text(pre + '\n' + body + '\n' + post, encoding='utf-8')
    return project, main_name, note


def build_report(p, main_name, compiled, layout_report, open_issues, engine):
    lines = ['# 排版与导出报告\n',
             f'- 主文件：{main_name}',
             f"- 编译引擎：{engine or '未找到本机 LaTeX'}",
             f"- 源码生成：完成（仅替换模板标记区间）",
             f"- 编译状态：{'成功，已产出 PDF' if compiled else ('未执行或未成功（见 layout-report.md）' if engine else '未执行（本机未检测到 LaTeX）')}",
             f"- 格式检查：见 latex-project.zip 中的 figure-audit.md",
             f"- 未解决问题：{len(open_issues)} 项（来自全文检查的“必须处理”）\n"]
    for i in open_issues[:20]:
        lines.append(f"- {i.get('message')}")
    lines.append('\n正式成果保留：LaTeX 项目包、编译成功时的 PDF、本检查说明。'
                 '编译通过不等于符合官方格式；最终版面请在你的可信 LaTeX 环境复核。'
                 'Word 导出需独立方案并核验，本应用不承诺 PDF→Word 保真。\n')
    return '\n'.join(lines)


def build_export(app, p, job, payload, fetch, save_fn):
    import writing, review
    app.checkpoint(job, 0, fetch=fetch, save_fn=save_fn)
    project, main_name, note = render_source(app, p)
    body = review.full_body(p)
    if not body.strip():
        raise ValueError('还没有可导出的正文，请先在“全文写作”中生成并采纳章节。')
    try:
        (project / 'figure-audit.md').write_text(writing.audit_figures_tables(body, project, {'paper_kind': p['paper_kind']}), encoding='utf-8')
    except Exception:
        pass
    app.checkpoint(job, 0, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 1, fetch=fetch, save_fn=save_fn)
    engine, _ = app.latex_engine()
    targets = payload.get('targets') or []
    compiled = None
    if engine and 'pdf' not in targets:
        # default: compile when an engine exists unless the caller explicitly omits pdf
        targets = ['latex-zip', 'pdf']
    compiled, layout_report = (None, '# PDF 编译与版式检查\n\n- 未请求编译。\n')
    if engine and 'pdf' in targets:
        compiled, layout_report = writing.compile_pdf(project, main_name, app)
    (project / 'layout-report.md').write_text(layout_report, encoding='utf-8')
    app.checkpoint(job, 1, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 2, fetch=fetch, save_fn=save_fn)
    open_issues = [i for i in ((p.get('check_report') or {}).get('items') or []) if i.get('severity') == 'must']
    if not p.get('check_report'):
        open_issues = []
    app.checkpoint(job, 2, 'done', fetch=fetch, save_fn=save_fn); app.checkpoint(job, 3, fetch=fetch, save_fn=save_fn)
    bdir = build_dir(app, p); bdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bdir / 'latex-project.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(project.iterdir()):
            if f.is_file() and f.suffix.lower() not in writing.BUILD_SUFFIXES and not f.name.endswith('.synctex.gz'):
                z.write(f, f.name)
    (bdir / 'build-report.md').write_text(build_report(p, main_name, compiled, layout_report, open_issues, engine), encoding='utf-8')
    names = ['latex-project.zip', 'build-report.md']
    if compiled:
        shutil.copy2(compiled, bdir / 'paper.pdf'); names.append('paper.pdf')
    p['build'] = {'plan': {'engine': engine or 'none', 'targets': targets}, 'artifacts': [{'name': n} for n in names],
                  'open_issues': open_issues, 'built_at': now()}
    p['artifacts'] = [{'name': n, 'kind': ('zip' if n.endswith('.zip') else 'pdf' if n.endswith('.pdf') else 'md'),
                       'url': f'/api/projects/{p["id"]}/artifacts/{n}', 'created_at': now()} for n in names]
    p['stage'] = 'done'
    app.event(job, '排版导出完成：' + '、'.join(names), save_fn)
    app.checkpoint(job, 3, 'done', fetch=fetch, save_fn=save_fn)
    save_project(app, p)
    if scratch_exists(project):
        shutil.rmtree(project.parent, ignore_errors=True)


def scratch_exists(project):
    return project.parent.exists()


# ---------------------------------------------------------------- routing

def post_route(app, p, suffix, payload):
    """Dispatch /api/projects/<pid><suffix> POST requests. Returns (status, body)."""
    payload = payload if isinstance(payload, dict) else {}
    pid = p['id']
    if suffix in ('/update',):
        p = update_project(app, pid, payload)
        return 200, public_project(p)
    if suffix == '/files':
        p = add_files(app, pid, str(payload.get('zone', '')), payload.get('files'))
        return 200, public_project(p)
    m = re.fullmatch(r'/files/([a-f0-9]{32})/delete', suffix)
    if m:
        p = delete_file(app, pid, m[1])
        return 200, public_project(p)
    if suffix == '/template':
        p['template'] = template_check(app, p, payload.get('file_id'), payload.get('main'))
        save_project(app, p)
        return 200, {'template': p['template']}
    if suffix == '/rules':
        p['rules_extra'] = str(payload.get('extra', ''))[:4000]
        p['rules'] = rules_checklist(app, p)
        save_project(app, p)
        return 200, {'rules': p['rules']}
    if suffix == '/references':
        p['references_manual'] = [str(x)[:200] for x in (payload.get('manual') or [])][:100]
        p['references'] = references_registry(app, p)
        save_project(app, p)
        return 200, {'references': p['references']}
    if suffix == '/mainline':
        if payload.get('action') == 'save':
            p['mainline'] = payload.get('mainline') or p.get('mainline')
            save_project(app, p)
            return 200, {'mainline': p['mainline']}
        job = start_job(app, p, 'mainline')
        return 202, {'job': job}
    if suffix == '/outline':
        if payload.get('action') in ('save', 'move', 'add', 'remove'):
            import outline
            items = payload.get('items') if payload.get('items') is not None else (p.get('outline') or {}).get('items')
            items = outline.normalize_items(items, p['paper_kind'])
            p['outline'] = {'items': items, 'reading_order': outline.reading_order(items),
                            'writing_order': outline.writing_order(items), 'source': 'manual', 'updated_at': now()}
            save_project(app, p)
            return 200, {'outline': p['outline']}
        job = start_job(app, p, 'outline')
        return 202, {'job': job}
    m = re.fullmatch(r'/sections/([A-Za-z0-9_]{1,32})', suffix)
    if m:
        sid = m[1]
        if payload.get('action') in (None, 'draft'):
            job = start_job(app, p, 'section', target=sid, payload={'sid': sid, 'instruction': payload.get('instruction', '')})
            return 202, {'job': job}
        p = apply_decision(app, p, sid, payload)
        return 200, {'sections': p['sections'], 'outline': p.get('outline')}
    if suffix == '/figures':
        p = insert_figure(app, p, payload)
        return 200, {'figures': p['figures']}
    if suffix == '/polish':
        job = start_job(app, p, 'polish', payload=payload)
        return 202, {'job': job}
    m = re.fullmatch(r'/revisions/([A-Za-z0-9_]{1,32})/decide', suffix)
    if m:
        p = decide_revision(app, p, m[1], payload)
        return 200, {'revisions': p['revisions'], 'sections': p['sections']}
    if suffix == '/check':
        job = start_job(app, p, 'check', payload=payload)
        return 202, {'job': job}
    if suffix == '/build':
        job = start_job(app, p, 'build', payload=payload)
        return 202, {'job': job}
    m = re.fullmatch(r'/jobs/([a-f0-9]{32})/cancel', suffix)
    if m:
        p2 = get_project(app, pid)
        job = p2.get('active_job')
        if not job or job['id'] != m[1]:
            raise ValueError('作业不存在')
        job['cancel_requested'] = True
        save_project(app, p2)
        return 200, {'message': '已请求取消，将在当前步骤返回后停止'}
    raise ValueError('接口不存在')


def start(app):
    """Bootstrap on startup: project dir, scratch cleanup, interrupted-job recovery."""
    projects_dir(app).mkdir(parents=True, exist_ok=True)
    try:
        import writing
        writing.start_cleanup(projects_dir(app))
    except Exception:
        pass
    for p in list_projects(app):
        job = p.get('active_job')
        if job and job.get('status') in ('queued', 'running', 'cancelling'):
            job.update(status='interrupted', message='服务已重启，作业中断。已完成步骤保留，可重试。')
            for s in job.get('steps', []):
                if s['status'] == 'running':
                    s['status'] = 'interrupted'
            for s in job.get('steps', []):
                if s['status'] == 'pending':
                    s['status'] = 'skipped'
            p['message'] = '作业已中断，可重试。'
            save_project(app, p)

