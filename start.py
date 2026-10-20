"""Load local .env without an additional dependency, then start loopback service."""
import os, runpy, sys, webbrowser
from pathlib import Path
root=Path(__file__).resolve().parent
env_file=Path(os.environ.get('PINKPIG_ENV_FILE') or os.environ.get('MATHM_ENV_FILE') or str(root/'.env'))
for line in env_file.read_text().splitlines() if env_file.exists() else []:
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line:continue
    key,value=line.split('=',1);key=key.strip();value=value.strip()
    if key.startswith(('PINKPIG_','MATHM_','OPENAI_')):os.environ.setdefault(key,value.strip('"\''))
os.environ.setdefault('PINKPIG_ENV_FILE',str(env_file))
if '--open' in sys.argv:
    import threading
    port=os.environ.get('PINKPIG_PORT') or os.environ.get('MATHM_PORT') or '8765'
    threading.Timer(1.5,lambda:webbrowser.open('http://127.0.0.1:'+port)).start()
runpy.run_path(str(root/'app.py'),run_name='__main__')
