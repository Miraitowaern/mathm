"""Desktop adapter: bundled runtime, random loopback port, persistent per-user data."""
import json, os, shutil, sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
support=Path(os.environ['PINKPIG_DESKTOP_SUPPORT']);support.mkdir(parents=True,exist_ok=True)
def migrate(source,db_target=None):
    if not source.exists():return
    if not (support/'data').exists() and (source/'data').exists():shutil.copytree(source/'data',support/'data')
    if not (support/'.env').exists() and (source/'.env').exists():
        shutil.copy2(source/'.env',support/'.env');os.chmod(support/'.env',0o600)
# Bring over the previous (MathM) desktop profile first, then the original web layout.
migrate(Path.home()/'Library/Application Support/MathM')
migrate(Path.home()/'mathm')
if (support/'.env').exists():
    for line in (support/'.env').read_text().splitlines():
        line=line.strip()
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1)
            if k.strip().startswith(('PINKPIG_','MATHM_','OPENAI_')):os.environ.setdefault(k.strip(),v.strip().strip('\"\''))
os.environ['PINKPIG_DATA_DIR']=str(support/'data')
os.environ.setdefault('PINKPIG_SKILLS_DIR',os.environ['PINKPIG_BUNDLED_SKILLS'])
os.environ['PINKPIG_ENV_FILE']=str(support/'.env')
import app
app.init()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
ready=Path(os.environ['PINKPIG_READY_FILE'])
ready.write_text(json.dumps({'port':server.server_port,'pid':os.getpid()}))
print('pinkpig 科研平台 ready on port',server.server_port,flush=True)
server.serve_forever()
