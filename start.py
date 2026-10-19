"""Load local .env without an additional dependency, then start loopback service."""
import os, runpy, sys, webbrowser
from pathlib import Path
root=Path(__file__).resolve().parent
for line in (root/'.env').read_text().splitlines() if (root/'.env').exists() else []:
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line:continue
    key,value=line.split('=',1);key=key.strip();value=value.strip()
    if key.startswith(('MATHM_','OPENAI_')):os.environ.setdefault(key,value.strip('"\''))
if '--open' in sys.argv:
    import threading
    threading.Timer(1.5,lambda:webbrowser.open('http://127.0.0.1:'+os.environ.get('MATHM_PORT','8765'))).start()
runpy.run_path(str(root/'app.py'),run_name='__main__')
