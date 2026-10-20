"""Full-text checks (step 8): deterministic items + merge/render for the AI items.

The deterministic part runs with no model configured at all; the AI part, when
available, only adds semantic items. Both are labelled ``source`` so the UI can
separate "deterministic check" from "AI review", matching the app's existing
honesty boundary.
"""
from __future__ import annotations
import re
import outline, writing


def full_body(p):
    """Concatenate adopted / draft sections in outline (reading) order."""
    items = ((p.get('outline') or {}).get('items')) or []
    sections = p.get('sections') or {}
    bodies = []
    for it in items:
        sec = sections.get(it['sid'])
        if sec and (sec.get('body_latex') or '').strip():
            bodies.append(sec['body_latex'])
    if not bodies:
        bodies = [s.get('body_latex', '') for s in sections.values() if (s.get('body_latex') or '').strip()]
    return '\n\n'.join(bodies)


def _item(category, severity, message, suggestion, quote='', sid=None, line=None, source='deterministic'):
    return {'id': outline._sid(f'{category}{message}{quote}'), 'category': category, 'severity': severity,
            'source': source, 'location': {'sid': sid, 'line': line, 'quote': str(quote)[:80]},
            'message': message, 'evidence': '', 'suggestion': suggestion, 'related': []}


def deterministic_checks(p, scope=None):
    """Rule-based checks that never require a model."""
    items = []
    body = full_body(p)
    for m in re.finditer(r'(待补充|待确认|TODO)', body):
        line = body.count('\n', 0, m.start()) + 1
        items.append(_item('待补充', 'must', f'正文存在未补齐占位“{m.group(1)}”。',
                           '补齐证据，或明确说明该项无法提供。', body[max(0, m.start() - 16):m.start() + 18], line=line))
    items += outline.crossref_audit(body)
    refs = p.get('references') or {}
    for entry in refs.get('missing') or []:
        items.append(_item('图表引用', 'must', f'正文引用了未提供的参考文献键：{entry.get("key")}。',
                           '补充真实文献条目，或移除该引用。', str(entry.get('key'))))
    for key in (refs.get('stats') or {}).get('duplicates') or []:
        items.append(_item('参考文献', 'should', f'参考文献存在重复键：{key}。', '合并或改为唯一键。', key))
    for it in (p.get('rules') or {}).get('items') or []:
        if it.get('verified') != 'fulfilled':
            items.append(_item('格式要求', 'verify', f'格式要求未核验：{it.get("requirement")}。',
                               '按上传规范人工核对；未核验不代表不合规。', str(it.get('requirement'))[:40]))
    flat = re.sub(r'\s+', '', body)
    if flat:
        for kw in ('摘要', '结论', '参考文献'):
            if kw not in flat:
                items.append(_item('问题结论对应', 'verify', f'正文未检出“{kw}”。',
                                   '人工确认是否缺失或命名不同。', kw))
    if scope and scope.get('kind') == 'sections' and scope.get('sids'):
        sids = set(scope['sids'])
        items = [i for i in items if not i['location'].get('sid') or i['location']['sid'] in sids]
    return items


def merge(ai_items, det_items):
    """Deduplicate by (category, quote prefix, message prefix), keeping both sources."""
    out = list(det_items)
    seen = {(i['category'], (i['location'].get('quote') or '')[:24], i['message'][:20]) for i in out}
    for a in ai_items or []:
        a.setdefault('id', outline._sid(f"{a.get('category','')}{a.get('message','')}"))
        a.setdefault('location', {})
        a['location'].setdefault('quote', '')
        key = (a.get('category', ''), (a['location'].get('quote') or '')[:24], (a.get('message') or '')[:20])
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    order = {'must': 0, 'should': 1, 'verify': 2}
    return sorted(out, key=lambda i: order.get(i.get('severity', 'verify'), 3))


def summary(items):
    return {'must': sum(i.get('severity') == 'must' for i in items),
            'should': sum(i.get('severity') == 'should' for i in items),
            'verify': sum(i.get('severity') == 'verify' for i in items),
            'deterministic': sum(i.get('source') == 'deterministic' for i in items),
            'ai': sum(i.get('source') == 'ai' for i in items)}


def render(report):
    labels = {'must': '必须处理', 'should': '建议修改', 'verify': '待人工核验'}
    lines = ['# 全文检查报告\n',
             f"- 运行时间：{report.get('run_at','')}",
             f"- 模式：{'确定性检查 + AI 语义补充' if report.get('model_used') else '确定性检查（未调用模型）'}",
             f"- 输入截断：{'是' if report.get('truncated') else '否'}",
             f"- 计数：必须处理 {report['summary']['must']} / 建议修改 {report['summary']['should']} / 待人工核验 {report['summary']['verify']}"
             f"（确定性 {report['summary']['deterministic']} · AI {report['summary']['ai']}）\n"]
    for sev in ('must', 'should', 'verify'):
        group = [i for i in report.get('items', []) if i.get('severity') == sev]
        if not group:
            continue
        lines.append(f'## {labels[sev]}（{len(group)}）\n')
        for i in group:
            loc = i.get('location') or {}
            where = '、'.join(x for x in [loc.get('sid') or '', (f"第 {loc['line']} 行" if loc.get('line') else ''),
                                          (f"“{loc['quote']}”" if loc.get('quote') else '')] if x)
            lines.append(f"- [{i.get('source')}] {i.get('message')}（{where}）\n  - 建议：{i.get('suggestion','')}")
        lines.append('')
    lines.append('本报告区分确定性检查与 AI 审查；未核验项不代表不合规，AI 判断需人工确认。\n')
    return '\n'.join(lines)
