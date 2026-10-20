"""Deterministic, model-free structural comparison against reference papers.

The "对标对比" flow measures structure only (length, headings, figure/table numbering,
captions, references, page count). It deliberately claims nothing about paper quality
or award probability, and it never fabricates missing values.
"""
from __future__ import annotations
import re, shutil, zipfile
from pathlib import Path

CJK = re.compile(r'[\u4e00-\u9fff]')
NUM_HEADING = re.compile(r'^\s*(?:\d+(?:\.\d+){0,3}|[一二三四五六七八九十]+[、.)])\s*\S', re.M)
KEY_SECTIONS = ['摘要', '关键词', '参考文献', '附录', '问题重述', '问题分析', '模型假设',
                '符号说明', '模型的建立', '模型求解', '结果分析', '模型检验', '结论']
DIMENSIONS = [('提取字符数', 'characters'), ('汉字数', 'hanzi'), ('PDF 页数', 'pages'),
              ('疑似章节标题', 'headings'), ('图编号最大值', 'figures'), ('表编号最大值', 'tables'),
              ('图表题注候选行', 'caption_lines'), ('参考文献条目', 'references')]


def metrics(text, pages=None, suffix=None):
    """Structural signals that can be measured from extracted text; nothing inferred."""
    figures = [int(x) for x in re.findall(r'图\s*(\d+)', text)]
    tables = [int(x) for x in re.findall(r'表\s*(\d+)', text)]
    return {
        'characters': len(text),
        'hanzi': len(CJK.findall(text)),
        'pages': pages,
        'headings': len(NUM_HEADING.findall(text)),
        'figures': max(figures) if figures else 0,
        'tables': max(tables) if tables else 0,
        'caption_lines': len(re.findall(r'^\s*(?:图|表)\s*\d+', text, re.M)),
        'references': len(re.findall(r'\[\d+\]', text)),
        'sections': [s for s in KEY_SECTIONS if s in text],
    }


def _avg(rows, key):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return sum(vals) / len(vals) if vals else 0


def render(subject, baseline):
    """Side-by-side table plus an honest gap list (structure only)."""
    lines = ['# 对标对比报告（与优秀论文/基准分维度对照）\n',
             '> 说明：以下指标由文本提取得到，**仅反映结构层面**，不代表论文质量或获奖概率。'
             '图/表计数基于编号出现次数，扫描页或纯图片页无法计入；缺失值不臆造。\n',
             '## 待评论文\n']
    for r in subject:
        lines.append('- %s：%d 字符 / %d 汉字%s' %
                     (r['name'], r['characters'], r['hanzi'],
                      '，PDF %d 页' % r['pages'] if r.get('pages') else ''))
    lines.append('\n## 基准（优秀论文/参考）\n')
    for r in baseline:
        lines.append('- %s：%d 字符 / %d 汉字%s' %
                     (r['name'], r['characters'], r['hanzi'],
                      '，PDF %d 页' % r['pages'] if r.get('pages') else ''))
    lines.append('\n## 分维度对照\n')
    lines.append('| 维度 | 待评论文（均值） | 基准（均值） |')
    lines.append('|---|---|---|')
    for label, key in DIMENSIONS:
        sv = _avg(subject, key); bv = _avg(baseline, key)
        lines.append('| %s | %s | %s |' % (label, ('%.1f' % sv) if sv else '—', ('%.1f' % bv) if bv else '—'))
    lines.append('\n## 差距清单（供参考）\n')
    gaps = []
    se, be = _avg(subject, 'hanzi'), _avg(baseline, 'hanzi')
    if be and se < 0.7 * be:
        gaps.append('篇幅：待评论文汉字数约为基准的 %.0f%%，显著偏薄，建议补充建模推导、结果分析与检验。' % (100 * se / be))
    if _avg(subject, 'figures') < _avg(baseline, 'figures'):
        gaps.append('图：待评论文图数量少于基准，建议补充关键结果图与示意图（真实数据）。')
    if _avg(subject, 'tables') < _avg(baseline, 'tables'):
        gaps.append('表：待评论文表数量少于基准，建议补充结果对比表。')
    if _avg(subject, 'references') < _avg(baseline, 'references'):
        gaps.append('参考文献：待评论文条目少于基准，建议补充真实来源并在正文标注。')
    base_sections = set()
    for r in baseline:
        base_sections.update(r['sections'])
    for r in subject:
        missing = [s for s in base_sections if s not in r['sections']]
        if missing:
            gaps.append('%s：未检出基准中出现的小节关键词：%s。' % (r['name'], '、'.join(missing)))
    if not gaps:
        gaps.append('未发现明显的结构性差距（仅就以上可测维度而言）。')
    lines.extend('- ' + g for g in gaps)
    lines.append('\n---\n本报告为确定性本地计算，未调用模型，未核验图片内容、数据真实性与官方规范；'
                 '请结合人工判断与上传的竞赛规范使用。\n')
    return '\n'.join(lines)


def run(app, t):
    folder = app.DATA / t['id']; scratch = folder / 'scratch'; project = scratch / 'project'
    t.update(status='running', report=None, progress=0, artifacts=[])
    for s in t['steps']:
        s['status'] = 'pending'
    app.save(t)
    try:
        if scratch.exists():
            shutil.rmtree(scratch)
        project.mkdir(parents=True)
        app.checkpoint(t, 0); app.event(t, '读取待评论文与基准论文；不保存解析副本')
        docs = []
        for f in t['files']:
            source = folder / (f['id'] + f['suffix'])
            text, notes, pages = app.extract(source, f['suffix'])
            f.update(characters=len(text), pages=pages, notes=notes)
            docs.append({'file': f, 'text': text})
            (folder / (f['id'] + '.txt')).write_text(text)
        subject = [d for d in docs if d['file']['role'] == 'paper']
        baseline = [d for d in docs if d['file']['role'] == 'support']
        if not subject or not baseline:
            raise ValueError('对标对比需要一份“论文”（待评论文）与至少一份“支撑材料”（优秀论文/基准）')
        app.checkpoint(t, 0, 'done'); app.checkpoint(t, 1); app.event(t, '按确定性指标提取各文档结构特征')
        def row(d):
            m = metrics(d['text'], d['file'].get('pages'), d['file']['suffix'])
            m['name'] = d['file']['name']
            return m
        subject_m = [row(d) for d in subject]; base_m = [row(d) for d in baseline]
        app.checkpoint(t, 1, 'done'); app.checkpoint(t, 2); app.event(t, '生成对照表与差距清单')
        report = render(subject_m, base_m)
        (project / 'comparison.md').write_text(report, encoding='utf-8')
        app.checkpoint(t, 2, 'done'); app.checkpoint(t, 3)
        with zipfile.ZipFile(scratch / 'comparison.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            for x in sorted(project.iterdir()):
                if x.is_file():
                    z.write(x, x.name)
        (scratch / 'comparison.zip').replace(folder / 'comparison.zip')
        (folder / 'comparison.md').write_text(report, encoding='utf-8')
        (folder / 'report.md').write_text(report, encoding='utf-8')
        t['report'] = report
        t['artifacts'] = [{'name': n, 'url': f'/api/tasks/{t["id"]}/artifacts/{n}'}
                          for n in ('comparison.md', 'report.md', 'comparison.zip')]
        app.checkpoint(t, 3, 'done'); t['status'] = 'completed'; app.event(t, '对标对比完成，报告已保存')
    except Exception as e:
        t['status'] = 'cancelled' if isinstance(e, InterruptedError) else 'failed'
        for s in t['steps']:
            if s['status'] == 'running':
                s['status'] = 'failed'
        app.event(t, str(e)[:300] if isinstance(e, (ValueError, InterruptedError, UnicodeError)) else '对标对比失败：' + type(e).__name__)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
