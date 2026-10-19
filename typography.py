"""Validated typography and deterministic local presentation commands."""
import re
LATIN=('inherit','Arial','Helvetica','Times New Roman','DejaVu Sans','DejaVu Serif')
CJK=('inherit','Songti SC','STSong','PingFang SC','Heiti SC')
SIZES=('inherit','7','8','9','10','10.5','11','12','14','16')

def settings(raw):
    result={k:raw.get(k,default) for k,default in [('font_latin','inherit'),('font_cjk','inherit'),('font_size','inherit')]}
    for k,choices in [('font_latin',LATIN),('font_cjk',CJK),('font_size',SIZES)]:
        if result[k] not in choices:raise ValueError('无效的字体设置：'+k)
    text=raw.get('instructions','')
    if not isinstance(text,str) or len(text)>4000:raise ValueError('补充提示词最多4000字')
    result['instructions']=text.strip()
    return result

def latex_wrap(body,o,preamble=None):
    custom=any(o.get(k,'inherit')!='inherit' for k in ('font_latin','font_cjk','font_size'))
    if not custom:return body
    if preamble is not None:
        if o.get('font_latin','inherit')!='inherit' and not re.search(r'fontspec|ctex|xeCJK',preamble):
            raise ValueError('模板未加载 fontspec/ctex；请选择跟随模板，或先在模板中加载字体支持（XeLaTeX）')
        if o.get('font_cjk','inherit')!='inherit' and not re.search(r'ctex|xeCJK',preamble):
            raise ValueError('模板未加载 ctex/xeCJK；中文字体请选择跟随模板，或先补充模板字体支持')
    lines=[r'\begingroup']
    if o.get('font_latin','inherit')!='inherit':lines.append(r'\fontspec{'+o['font_latin']+'}')
    if o.get('font_cjk','inherit')!='inherit':lines.append(r'\CJKfontspec{'+o['font_cjk']+'}')
    if o.get('font_size','inherit')!='inherit':
        size=float(o['font_size']);lines.append(r'\fontsize{'+f'{size:g}'+'}{'+f'{size*1.3:g}'+r'}\selectfont')
    return '\n'.join(lines)+'\n'+body+'\n'+r'\endgroup'+'\n'

def commands(o):
    mode=o['mode'];out={}
    for line in re.split(r'[\n；;]+',o.get('instructions','')):
        line=line.strip().rstrip('。')
        if not line:continue
        if mode=='figure':
            if line in ('去掉网格','隐藏网格','不显示网格'):out['grid']=False
            elif line in ('显示网格','保留网格'):out['grid']=True
            elif line in ('图例放在底部','图例放到底部','图例置底'):out['legend']='bottom'
            elif line in ('图例放在顶部','图例置顶'):out['legend']='top'
            elif line in ('隐藏图例','不显示图例'):out['legend']='none'
            elif line in ('显示数据点','显示圆点'):out['markers']=True
            elif line in ('不显示数据点','隐藏数据点'):out['markers']=False
            elif re.fullmatch(r'(?:标题|横轴标签|纵轴标签)[:：].+',line):
                key,value=re.split('[:：]',line,maxsplit=1);out[{'标题':'title','横轴标签':'x_label','纵轴标签':'y_label'}[key]]=value.strip()[:150]
            else:raise ValueError('暂不支持这条本地图片指令：'+line[:60]+'。请使用提示窗列出的指令')
        elif mode=='table':
            if line in ('表头加粗','加粗表头'):out['bold_header']=True
            elif line in ('表头不加粗','不加粗表头'):out['bold_header']=False
            elif line in ('数字右对齐','数值列右对齐'):out['numeric_right']=True
            elif line in ('所有列居中','表格内容居中'):out['alignment']='center'
            elif line in ('所有列左对齐',):out['alignment']='left'
            elif re.fullmatch(r'表题[:：].+',line):out['caption']=re.split('[:：]',line,maxsplit=1)[1].strip()[:600]
            else:raise ValueError('暂不支持这条本地表格指令：'+line[:60]+'。请使用提示窗列出的指令')
    return out
