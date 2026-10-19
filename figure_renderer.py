"""Reproduce: python plot.py (requires matplotlib). Fixed renderer, no model code."""
import csv,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
ROOT=Path(__file__).resolve().parent

def main():
    options=json.loads((ROOT/'settings.json').read_text())
    with (ROOT/'source-data.csv').open(encoding='utf-8-sig',newline='') as f:
        data=list(csv.DictReader(f))
    for path in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/STHeiti Light.ttc','/System/Library/Fonts/Supplemental/Songti.ttc']:
        if Path(path).exists():font_manager.fontManager.addfont(path)
    latin=options.get('font_latin','inherit');cjk=options.get('font_cjk','inherit')
    for family in [latin,cjk]:
        if family!='inherit':
            try:font_manager.findfont(font_manager.FontProperties(family=[family]),fallback_to_default=False)
            except ValueError:raise ValueError('所选字体未安装：'+family+'；请更换字体或选择默认字体')
    available={f.name for f in font_manager.fontManager.ttflist}
    default_cjk=next((f for f in ['PingFang SC','Songti SC','Heiti SC'] if f in available),'DejaVu Sans')
    families=[latin if latin!='inherit' else 'Arial',cjk if cjk!='inherit' else default_cjk,'DejaVu Sans']
    size=options.get('font_size','inherit');size=8 if size=='inherit' else float(size)
    plt.rcParams.update({'font.family':families,'font.size':size,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'svg.fonttype':'none','text.usetex':False,'axes.unicode_minus':False})
    fig,ax=plt.subplots(figsize=(3.5,2.8),layout='constrained')
    palette=['#236B8E','#CF6B4C','#6A9473','#9B78A5','#C3A34E','#5E9BA4','#965B5B','#777777']
    kind=options['chart_type'];xs=[row[options['x_column']] for row in data]
    ys=options['y_columns'];positions=list(range(len(xs)))
    for i,yname in enumerate(ys):
        values=[float(row[yname]) for row in data]
        if kind=='bar':
            width=.8/len(ys);offset=(i-(len(ys)-1)/2)*width
            ax.bar([p+offset for p in positions],values,width=width,color=palette[i],label=yname)
        elif kind=='scatter':ax.scatter([float(x) for x in xs],values,s=16,color=palette[i],label=yname)
        else:ax.plot([float(x) for x in xs],values,lw=1.3,color=palette[i],label=yname,marker='o' if options.get('markers') else None)
    if kind=='bar':ax.set_xticks(positions,xs,rotation=45 if len(xs)>6 else 0,ha='right' if len(xs)>6 else 'center',rotation_mode='anchor')
    ax.set_xlabel(options['x_label'] or options['x_column']);ax.set_ylabel(options['y_label'] or (ys[0] if len(ys)==1 else 'Value'))
    if len(ys)>1 and options.get('legend')!='none':
        bottom=options.get('legend')=='bottom'
        ax.legend(frameon=False,loc='upper center' if bottom else 'lower left',bbox_to_anchor=(0.5,-0.27) if bottom else (0,1.01),ncols=min(3,len(ys)),fontsize=max(7,size-1))
    if options.get('title'):fig.suptitle(options['title'],fontsize=size+1)
    ax.tick_params(direction='out',width=.6);ax.grid(visible=options.get('grid',True),axis='y',**({'alpha':.16,'lw':.5} if options.get('grid',True) else {}));ax.set_axisbelow(True)
    fig.canvas.draw()
    fig.savefig(ROOT/'figure.pdf')
    fig.savefig(ROOT/'figure.svg')
    fig.savefig(ROOT/'figure.png',dpi=600)
    plt.close(fig)
if __name__=='__main__':main()
