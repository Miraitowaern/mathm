"""Desktop adapter: bundled runtime, random loopback port, persistent per-user data."""
import json, os, shutil, sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
support=Path(os.environ['MATHM_DESKTOP_SUPPORT']);support.mkdir(parents=True,exist_ok=True)
legacy=Path.home()/'mathm'
# Migrate once; do not overwrite existing desktop data or embed personal data in the app.
if not (support/'data').exists() and (legacy/'data').exists():
    shutil.copytree(legacy/'data',support/'data')
    original=legacy/'data/mathm.sqlite3'
    if original.exists():
        with sqlite3.connect(original) as src,sqlite3.connect(support/'data/mathm.sqlite3') as dst:src.backup(dst)
if not (support/'.env').exists() and (legacy/'.env').exists():
    shutil.copy2(legacy/'.env',support/'.env');os.chmod(support/'.env',0o600)
if (support/'.env').exists():
    for line in (support/'.env').read_text().splitlines():
        line=line.strip()
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1)
            if k.strip().startswith(('MATHM_','OPENAI_')):os.environ.setdefault(k.strip(),v.strip().strip('\"\''))
os.environ['MATHM_DATA_DIR']=str(support/'data')
os.environ.setdefault('MATHM_SKILLS_DIR',os.environ['MATHM_BUNDLED_SKILLS'])
import app
app.init()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
ready=Path(os.environ['MATHM_READY_FILE'])
ready.write_text(json.dumps({'port':server.server_port,'pid':os.getpid()}))
print('MathM Desktop ready on port',server.server_port,flush=True)
server.serve_forever()
