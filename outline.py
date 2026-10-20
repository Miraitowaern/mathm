"""Deterministic outline, numbering and cross-reference helpers.

Pure functions: no model calls, no network, no IO. They give the project
workspace facts it can trust (section numbers, figure numbering, orphan/duplicate
labels, paragraph anchors) without ever fabricating content.
"""
from __future__ import annotations
import hashlib, re

_WRITING_PRIO = {'method': 1, 'results': 2, 'experiments': 3, 'discussion': 4, 'conclusion': 5,
                 'intro': 6, 'related-work': 7, 'abstract': 8, 'title': 9}


def _sid(seed):
    return hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]


def normalize_items(raw_items, paper_kind=None):
    """Clean model/user outline items, assign stable sids and prev/next links."""
    items = []
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get('title') or '').strip()[:120]
        if not title:
            continue
        items.append({
            'sid': str(raw.get('sid') or _sid(title + '#' + str(len(items))))[:32],
            'title': title,
            'question': str(raw.get('question') or '')[:300],
            'uses_materials': [str(x)[:64] for x in (raw.get('uses_materials') or []) if isinstance(x, str)][:20],
            'uses_figures': [str(x)[:32] for x in (raw.get('uses_figures') or []) if isinstance(x, str)][:20],
            'missing_evidence': [str(x)[:200] for x in (raw.get('missing_evidence') or []) if isinstance(x, str)][:20],
            'level': max(1, min(3, int(raw.get('level') or 1))) if str(raw.get('level') or '1').isdigit() else 1,
            'anchor': str(raw.get('anchor') or '')[:60],
        })
    seen = set()
    for it in items:
        while it['sid'] in seen:
            it['sid'] = _sid(it['title'] + it['sid'])
        seen.add(it['sid'])
    for i, it in enumerate(items):
        it['prev'] = items[i - 1]['sid'] if i > 0 else None
        it['next'] = items[i + 1]['sid'] if i + 1 < len(items) else None
    return items


def reading_order(items):
    return [it['sid'] for it in items]


def writing_order(items):
    """Suggested writing order: methods/results first, then discussion, intro, abstract/title."""
    return [it['sid'] for it in sorted(items, key=lambda it: (_WRITING_PRIO.get(it.get('anchor') or '', 5)))]


def section_numbers(items):
    """Section numbers derived from the actual outline order (level-aware)."""
    counts = [0, 0, 0]; out = {}
    for it in items:
        lvl = max(1, min(3, it.get('level', 1)))
        counts[lvl - 1] += 1
        for i in range(lvl, 3):
            counts[i] = 0
        out[it['sid']] = '.'.join(str(counts[i]) for i in range(lvl))
    return out


def figure_numbering(figures, items):
    """Number figures and tables by the reading position of the first section citing them."""
    order = {it['sid']: i for i, it in enumerate(items)}
    def first(d):
        cs = [c for c in (d.get('citing_sections') or []) if c in order]
        return min((order[c] for c in cs), default=10 ** 6)
    figs = sorted([f for f in figures if f.get('kind') != 'table'], key=lambda f: (first(f), f.get('created_at', '')))
    tabs = sorted([f for f in figures if f.get('kind') == 'table'], key=lambda f: (first(f), f.get('created_at', '')))
    return {'figures': {f['fid']: i + 1 for i, f in enumerate(figs)},
            'tables': {f['fid']: i + 1 for i, f in enumerate(tabs)}}


def crossref_audit(body, figures=None):
    """Orphan labels and dangling \\ref keys, as deterministic check items."""
    items = []
    labels = set(re.findall(r'\\label\{([^}]+)\}', body))
    refs = {k.strip() for keys in re.findall(r'\\(?:ref|autoref|eqref|pageref)\{([^}]+)\}', body) for k in keys.split(',')}
    for lab in sorted(labels - refs):
        items.append({'category': '图表引用', 'severity': 'should', 'source': 'deterministic',
                      'location': {'quote': lab}, 'evidence': '',
                      'message': f'label {lab} 未被正文引用（孤儿），请补充引用或删除该图表。',
                      'suggestion': '补充“如图/表 … 所示”的引用。', 'related': []})
    for r in sorted(refs - labels):
        items.append({'category': '图表引用', 'severity': 'must', 'source': 'deterministic',
                      'location': {'quote': r}, 'evidence': '',
                      'message': f'\\ref{{{r}}} 指向不存在的 label（悬空引用）。',
                      'suggestion': '修正引用键，或补充对应图表的 \\label。', 'related': []})
    return items


def paragraph_index(body):
    """Split a section body into paragraphs; pid = sha1 of the normalized first 40 chars."""
    out = []
    for chunk in re.split(r'\n\s*\n', body or ''):
        text = chunk.strip()
        if not text:
            continue
        norm = re.sub(r'\s+', '', text)[:40]
        out.append({'pid': _sid(norm), 'text': text})
    return out


def find_paragraph(body, pid):
    for para in paragraph_index(body):
        if para['pid'] == pid:
            return para['text']
    return None


def mainline_text(mainline):
    if not mainline:
        return '（尚未整理研究主线）'
    lines = [f"研究问题：{mainline.get('question','')}",
             f"方法与假设：{mainline.get('method','')}"]
    for a in mainline.get('assumptions') or []:
        lines.append(f"- 假设：{a}")
    if mainline.get('terms'):
        lines.append('术语/符号：' + '；'.join(f"{t.get('term')}({t.get('unit') or '无单位'})={t.get('definition')}" for t in mainline['terms']))
    for r in mainline.get('results') or []:
        lines.append(f"- 结果：{r.get('claim','')}（来源：{'真实' if r.get('source')=='real' else '未核验'}）")
    lines.append(f"结论边界：{mainline.get('bounds','')}")
    if mainline.get('missing_evidence'):
        lines.append('缺失证据：' + '；'.join(mainline['missing_evidence']))
    return '\n'.join(lines)


def mainline_gaps(mainline):
    """Rule-based gaps appended to the AI mainline's missing_evidence."""
    gaps = []
    if not mainline:
        return ['尚未整理研究主线。']
    if not (mainline.get('bounds') or '').strip():
        gaps.append('结论缺少适用边界（bounds）。')
    if not mainline.get('terms'):
        gaps.append('术语/符号表为空，后续章节无法统一口径。')
    for r in mainline.get('results') or []:
        if not r.get('evidence'):
            gaps.append(f"结果“{str(r.get('claim'))[:30]}”缺少证据引用。")
    return gaps
