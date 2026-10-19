"""Import explicitly selected, locally owned/licensed skills. No network access."""
import argparse,shutil
from pathlib import Path
ALLOW={'nature-writing','nature-polishing','nature-figure','nature-shared','mathm-latex-writing'}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path,help='local skills directory')
    p.add_argument('--destination',type=Path,default=Path(__file__).resolve().parents[1]/'skills')
    p.add_argument('--names',nargs='+',required=True,help='exact skill directory names to import')
    a=p.parse_args()
    for name in a.names:
        if '/' in name or '\\' in name or not (name in ALLOW or name.startswith('hwb-')):p.error('unsupported skill name: '+name)
        if not (a.source/name).is_dir():p.error('skill not found: '+name)
        if (a.destination/name).exists():p.error('destination exists; choose another destination: '+name)
    for name in a.names:shutil.copytree(a.source/name,a.destination/name,ignore=shutil.ignore_patterns('__pycache__','.DS_Store','INSTALLATION.json'))
    print('Imported:',', '.join(a.names))
if __name__=='__main__':main()
