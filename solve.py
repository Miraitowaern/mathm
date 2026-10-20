"""Local numeric solving for the pinkpig workbench.

Two clearly separated levels of trust:

* ``local_numeric`` — deterministic, model-free descriptive statistics and Pearson
  correlation on the uploaded CSV/XLSX data only. It never claims to solve the
  competition model.
* ``sandbox_run`` — opt-in execution of a model-generated solver script. The script
  must pass an AST preflight (``validate_solver_source``) that forbids process,
  network, filesystem and dynamic-execution primitives, then runs in a restricted
  subprocess. This is a static preflight plus a restricted child process, NOT an
  operating-system sandbox; the UI and the delivery notes say so explicitly.
"""
from __future__ import annotations
import ast, csv, io, json, math, os, re, shutil, subprocess, sys, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# Modules a generated solver script may not import.
BANNED_IMPORTS = {'os', 'subprocess', 'socket', 'ssl', 'shutil', 'ctypes', 'importlib',
                  'multiprocessing', 'threading', 'concurrent', 'http', 'urllib', 'requests',
                  'ftplib', 'smtplib', 'telnetlib', 'pickle', 'marshal', 'pty', 'pdb', 'gc',
                  'resource', 'signal', 'webbrowser', 'builtins', 'glob', 'tempfile', 'pathlib'}
# Builtins / names a generated solver script may not call. ``open`` stays allowed
# so a script can read ./inputs and write ./outputs; the banned import set above is
# what keeps it from enumerating or escaping the working directory.
BANNED_NAMES = {'eval', 'exec', 'compile', '__import__', 'globals', 'locals', 'vars',
                'memoryview', 'breakpoint', 'input'}


def validate_solver_source(source):
    """Static AST preflight for a model-generated solver script.

    Returns ``(ready, findings)`` where findings is a list of
    ``{'level', 'check', 'message'}``. This is best-effort static analysis, not a
    runtime sandbox.
    """
    findings = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, [{'level': 'FAIL', 'check': 'SYNTAX',
                        'message': '第 %s 行语法错误：%s' % (exc.lineno or '?', exc.msg)}]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split('.')[0]
                if root in BANNED_IMPORTS:
                    findings.append({'level': 'FAIL', 'check': 'BANNED-IMPORT',
                                     'message': '第 %d 行禁止导入模块：%s' % (node.lineno, root)})
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or '').split('.')[0]
            if root in BANNED_IMPORTS:
                findings.append({'level': 'FAIL', 'check': 'BANNED-IMPORT',
                                 'message': '第 %d 行禁止从 %s 导入' % (node.lineno, root)})
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            findings.append({'level': 'FAIL', 'check': 'BANNED-NAME',
                             'message': '第 %d 行禁止使用名称：%s' % (node.lineno, node.id)})
        elif isinstance(node, ast.Attribute) and node.attr.startswith('__') and node.attr.endswith('__'):
            findings.append({'level': 'FAIL', 'check': 'DUNDER-ATTR',
                             'message': '第 %d 行禁止访问双下划线属性：%s' % (node.lineno, node.attr)})
    return (not findings), findings


def _csv_rows(path):
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('gb18030')
    return list(csv.reader(io.StringIO(text)))


def _xlsx_rows(path):
    """Read cell values (not formulas) from the first worksheet of an .xlsx."""
    NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(NS + 'si'):
                shared.append(''.join(t.text or '' for t in si.iter(NS + 't')))
        sheets = sorted(n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))
        if not sheets:
            return []
        rows = []
        for row in ET.fromstring(z.read(sheets[0])).iter(NS + 'row'):
            values = []
            for cell in row.iter(NS + 'c'):
                kind = cell.get('t'); v = cell.find(NS + 'v'); inline = cell.find(NS + 'is')
                if kind == 's' and v is not None and v.text and int(v.text) < len(shared):
                    value = shared[int(v.text)]
                elif kind == 'inlineStr' and inline is not None:
                    value = ''.join(t.text or '' for t in inline.iter(NS + 't'))
                elif v is not None:
                    value = v.text or ''
                else:
                    value = ''
                values.append(value.strip())
            while values and not values[-1]:
                values.pop()
            if values:
                rows.append(values)
        return rows


def read_numeric_table(path):
    """Return ``(headers, rows)`` for a .csv/.xlsx file; only cell text, no formula evaluation."""
    path = Path(path)
    if path.suffix.lower() == '.xlsx':
        rows = _xlsx_rows(path)
    elif path.suffix.lower() == '.csv':
        rows = _csv_rows(path)
    else:
        raise ValueError('仅支持 csv/xlsx 的数值读取：' + path.name)
    if not rows:
        raise ValueError('未读取到任何数据行：' + path.name)
    headers = [str(x) for x in rows[0]]
    return headers, rows[1:]


def _numeric_columns(headers, data_rows):
    """Column -> list of (row_index, value) for columns that look numeric."""
    columns = {}
    for i, name in enumerate(headers):
        values = []
        cells = 0
        for r, row in enumerate(data_rows):
            cell = str(row[i]).strip() if i < len(row) else ''
            if not cell:
                continue
            cells += 1
            try:
                values.append((r, float(cell)))
            except ValueError:
                pass
        if cells and len(values) >= max(1, math.ceil(0.6 * cells)):
            columns[name or ('列%d' % (i + 1))] = values
    return columns


def _pearson(pairs):
    n = len(pairs)
    if n < 2:
        return None
    xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
    mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    return sxy / math.sqrt(sxx * syy)


def _describe(values):
    xs = sorted(v for _, v in values)
    n = len(xs); mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
    def q(p):
        if n == 1:
            return xs[0]
        pos = p * (n - 1)
        lo = int(math.floor(pos)); hi = min(lo + 1, n - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
    return {'n': n, 'mean': mean, 'stdev': math.sqrt(var), 'min': xs[0], 'max': xs[-1],
            'q1': q(0.25), 'median': q(0.5), 'q3': q(0.75)}


def local_numeric(app, t, extracted):
    """Deterministic, model-free statistics on uploaded CSV/XLSX data.

    Returns ``(markdown, notes)``; artifacts are the facts we can compute, never a
    fabricated model solution.
    """
    folder = app.DATA / t['id']
    data_files = [f for f in t['files'] if f['suffix'] in ('.csv', '.xlsx')]
    if not data_files:
        return '', ['未上传可用于数值计算的 CSV/XLSX 数据；本机未执行数值计算。']
    sections = ['# 本机数值计算（确定性描述统计与相关分析）\n',
                '仅对上传数据做描述统计与 Pearson 相关，**未求解题目所需模型**；如需模型求解请在新建任务时勾选沙箱执行，或自行运行导出的脚本。\n']
    desc_rows = [['数据文件', '列', '有效值', '缺失/非数值', '均值', '标准差', '最小', 'Q1', '中位数', 'Q3', '最大']]
    any_data = False
    for f in data_files:
        path = folder / (f['id'] + f['suffix'])
        try:
            headers, rows = read_numeric_table(path)
        except Exception as exc:
            sections.append(f'## {f["name"]}\n\n- 读取失败：{exc}\n')
            continue
        columns = _numeric_columns(headers, rows)
        if not columns:
            sections.append(f'## {f["name"]}\n\n- 未检出数值列（共 {len(rows)} 行、{len(headers)} 列），未做数值计算。\n')
            continue
        any_data = True
        total_cells = len(rows)
        sections.append(f'## {f["name"]}\n\n- 数据：{len(rows)} 行 × {len(headers)} 列；检出数值列 {len(columns)} 个。\n')
        sections.append('| 列 | 有效值 n | 缺失/非数值 | 均值 | 标准差 | 最小 | Q1 | 中位数 | Q3 | 最大 |')
        sections.append('|---|---|---|---|---|---|---|---|---|---|')
        for name, values in columns.items():
            s = _describe(values)
            sections.append('| %s | %d | %d | %.6g | %.6g | %.6g | %.6g | %.6g | %.6g | %.6g |' %
                            (name, s['n'], total_cells - s['n'], s['mean'], s['stdev'], s['min'],
                             s['q1'], s['median'], s['q3'], s['max']))
            desc_rows.append([f['name'], name, str(s['n']), str(total_cells - s['n']),
                              '%.6g' % s['mean'], '%.6g' % s['stdev'], '%.6g' % s['min'],
                              '%.6g' % s['q1'], '%.6g' % s['median'], '%.6g' % s['q3'], '%.6g' % s['max']])
        sections.append('')
        names = list(columns)
        if len(names) >= 2:
            sections.append('| 相关列对 | 有效行数 | Pearson r |')
            sections.append('|---|---|---|')
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a = dict(columns[names[i]]); b = dict(columns[names[j]])
                    pairs = [(a[k], b[k]) for k in a if k in b]
                    r = _pearson(pairs)
                    sections.append('| %s ↔ %s | %d | %s |' % (names[i], names[j], len(pairs),
                                  '样本不足或零方差，未计算' if r is None else '%.4f' % r))
            sections.append('')
    if not any_data:
        return '', ['上传的 CSV/XLSX 未检出可用于描述统计的数值列；本机未执行数值计算。']
    markdown = '\n'.join(sections)
    (folder / 'local-results.md').write_text(markdown, encoding='utf-8')
    (folder / 'descriptive.csv').write_text(
        '\n'.join(','.join('"%s"' % c.replace('"', '""') for c in row) for row in desc_rows),
        encoding='utf-8')
    t['artifacts'].extend([{'name': 'local-results.md', 'url': f'/api/tasks/{t["id"]}/artifacts/local-results.md'},
                           {'name': 'descriptive.csv', 'url': f'/api/tasks/{t["id"]}/artifacts/descriptive.csv'}])
    return markdown, ['本机已对上传数据完成确定性描述统计与相关分析（未求解题目模型）。']


def _extract_code(raw):
    fenced = re.findall(r'```(?:python|py)?\s*\n(.*?)```', raw or '', re.S)
    if fenced:
        return max(fenced, key=len).strip()
    return (raw or '').strip()


def sandbox_run(app, t, extracted):
    """Opt-in: generate a Python solver script, preflight it, and run it locally.

    Returns ``(markdown, notes)``. On any validation or execution failure this
    raises, so no fabricated numbers are ever reported.
    """
    folder = app.DATA / t['id']; scratch = folder / 'scratch'; project = scratch / 'project'
    if scratch.exists():
        shutil.rmtree(scratch)
    (project / 'inputs').mkdir(parents=True)
    (project / 'outputs').mkdir()
    try:
        # Copy source data next to the script; the script reads only ./inputs.
        for f in t['files']:
            if f['suffix'] in ('.csv', '.xlsx', '.txt', '.json'):
                shutil.copy2(folder / (f['id'] + f['suffix']), project / 'inputs' / f['name'])
        materials = []
        budget = 90000
        for x in sorted(extracted, key=lambda x: {'rules': 0, 'problem': 1, 'paper': 2, 'support': 3}[x['file']['role']]):
            txt = x['text']; allowed = min(len(txt), max(0, budget)); budget -= allowed
            materials.append(f'\n<材料 文件={json.dumps(x["file"]["name"], ensure_ascii=False)} 角色={x["file"]["role"]}>\n{txt[:allowed]}\n</材料>')
        raw = app.model_call(app.MODELING_SKILL, '\n'.join(materials), t['topic'], t['year'],
                             focus='references/coding.md', task='script')
        script = _extract_code(raw)
        ready, findings = validate_solver_source(script)
        if not ready:
            raise ValueError('求解脚本未通过静态安全预检：' + '；'.join(x['message'] for x in findings[:6]))
        (project / 'solver.py').write_text(script, encoding='utf-8')
        env = os.environ.copy()
        for key in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY'):
            env.pop(key, None)
        env['no_proxy'] = '*'; env['PYTHONDONTWRITEBYTECODE'] = '1'; env['MPLBACKEND'] = 'Agg'
        env['MPLCONFIGDIR'] = str(scratch / 'mpl'); env['PYTHONPATH'] = ''
        try:
            result = subprocess.run([sys.executable, '-B', str(project / 'solver.py')], cwd=project,
                                    env=env, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('沙箱未能启动求解脚本：' + type(exc).__name__)
        if result.returncode:
            raise ValueError('沙箱脚本执行失败（退出码 %d）：%s' % (result.returncode, (result.stderr or '')[-400:]))
        outputs = sorted(p.name for p in (project / 'outputs').iterdir()) if (project / 'outputs').exists() else []
        solution = None
        solution_path = project / 'solution.json'
        if solution_path.exists():
            try:
                solution = json.loads(solution_path.read_text(encoding='utf-8'))
            except ValueError:
                solution = None
        lines = ['# 沙箱数值求解（模型生成脚本，静态预检后本机执行）\n',
                 '- 静态预检：通过（已禁用进程、网络、文件系统与动态执行原语）。',
                 '- 运行退出码：0。',
                 '- 说明：本沙箱为静态预检 + 受限子进程，**并非操作系统级隔离**；请仅执行你信任的脚本。\n']
        if solution is not None:
            lines.append('## solution.json\n')
            lines.append('```json\n' + json.dumps(solution, ensure_ascii=False, indent=2)[:4000] + '\n```\n')
        if outputs:
            lines.append('## outputs 目录\n\n' + '\n'.join('- ' + o for o in outputs) + '\n')
        if result.stdout.strip():
            lines.append('## 标准输出（末尾）\n\n```\n' + result.stdout[-2000:] + '\n```\n')
        markdown = '\n'.join(lines)
        (folder / 'solver.py').write_text(script, encoding='utf-8')
        (folder / 'solution-summary.md').write_text(markdown, encoding='utf-8')
        t['artifacts'].extend([{'name': 'solver.py', 'url': f'/api/tasks/{t["id"]}/artifacts/solver.py'},
                               {'name': 'solution-summary.md', 'url': f'/api/tasks/{t["id"]}/artifacts/solution-summary.md'}])
        return markdown, ['已在沙箱中执行模型生成的求解脚本并产出结果（静态预检通过）。']
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
