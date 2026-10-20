"""Package PinkPig.app.

The bundled runtime must be a self-contained CPython 3.12: conda/homebrew
interpreters link their extensions against non-system dylibs (e.g. @rpath/libsqlite3.dylib)
and produce an app that crashes on other machines. Run with any interpreter; this
script selects a suitable one, or explains why none is available.
"""
from pathlib import Path
import glob,json,os,platform,plistlib,shutil,subprocess,sys

PY_TAG='3.12'
REQUIRED_MODULES=['pymupdf','docx','lxml','typing_extensions','matplotlib','numpy','PIL']
PROBE=('import json,sys,importlib.util as u;'
       'import _sqlite3 as s;'
       'print(json.dumps({"version":"%d.%d"%sys.version_info[:2],"prefix":sys.base_prefix,'
       '"deps":all(u.find_spec(m) for m in '+repr(REQUIRED_MODULES)+'),'
       '"sqlite3_file":getattr(s,"__file__","") or ""}))')

def candidate_info(python):
    """Probe an interpreter. Returns None when it cannot run or report itself."""
    try:result=subprocess.run([python,'-c',PROBE],capture_output=True,text=True,timeout=60)
    except (OSError,subprocess.SubprocessError):return None
    if result.returncode:return None
    try:return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError,ValueError):return None

def relocatable(sqlite3_file):
    """True when _sqlite3 is builtin, or links only against system libraries."""
    if not sqlite3_file:return True
    try:result=subprocess.run(['otool','-L',sqlite3_file],capture_output=True,text=True,timeout=20)
    except (OSError,subprocess.SubprocessError):return False
    deps=[line.strip().split(' ')[0] for line in result.stdout.splitlines()[1:] if line.strip()]
    return bool(deps) and all(dep.startswith(('/usr/lib/','/System/')) for dep in deps)

def interpreter_problems(info):
    """Human-readable reason this interpreter cannot be bundled, or '' when it is acceptable."""
    if info is None:return '无法运行，或不是可用的 Python 解释器'
    if info['version']!=PY_TAG:return '版本为 Python %s，需要 %s' % (info['version'],PY_TAG)
    if 'conda' in str(info['prefix']).lower():return 'conda/miniconda 环境不可重定位（扩展库依赖 @rpath 或非系统动态库）'
    if not info['deps']:return '缺少打包依赖：'+', '.join(REQUIRED_MODULES)
    if not relocatable(info['sqlite3_file']):return '_sqlite3 扩展链接到非系统库，打包后无法在其它机器加载'
    return ''

def candidates():
    """Known standalone CPython locations, then an already packaged self-contained runtime."""
    project=Path(__file__).resolve().parent.parent
    patterns=['~/.local/share/uv/python/*/bin/python3.12','~/.pyenv/versions/3.12*/bin/python3.12',
              '/usr/local/bin/python3.12','/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12',
              '/opt/homebrew/bin/python3.12']
    found=[]
    for pattern in patterns:found+=sorted(glob.glob(os.path.expanduser(pattern)))
    for name in ('PinkPig.app','MathM.app'):
        found.append(str(project/name/'Contents/Resources/runtime/bin/python3.12'))
    return found

def ensure_interpreter():
    """Select a bundlable CPython 3.12 (re-exec into it when needed), else fail clearly."""
    override=os.environ.get('PINKPIG_BUILD_PYTHON') or os.environ.get('MATHM_BUILD_PYTHON')
    if override:
        problem=interpreter_problems(candidate_info(override))
        if problem:raise SystemExit('PINKPIG_BUILD_PYTHON 指定的解释器不可用：\n  %s\n  原因：%s' % (override,problem))
        return
    problem=interpreter_problems(candidate_info(sys.executable))
    if not problem:return
    for alternative in candidates():
        if Path(alternative).resolve()==Path(sys.executable).resolve():continue
        if not Path(alternative).exists():continue
        if not interpreter_problems(candidate_info(alternative)):
            print('使用可打包解释器：'+alternative,flush=True)
            os.execve(alternative,[alternative,str(Path(__file__).resolve()),*sys.argv[1:]],
                      dict(os.environ,PINKPIG_BUILD_PYTHON=alternative))
    raise SystemExit(
        '无法用当前解释器构建 PinkPig.app，未生成任何产物。\n'
        '  当前解释器：%s\n  原因：%s\n'
        '需要一个自带标准库、不依赖 conda/homebrew 动态库的 CPython %s，且已安装：%s\n'
        '可选任一方式后重试：\n'
        '  1) 安装独立 CPython：uv python install %s（或从 python.org 安装）\n'
        '  2) 显式指定：PINKPIG_BUILD_PYTHON=/path/to/python%s python3 %s'
        % (sys.executable,problem,PY_TAG,', '.join(REQUIRED_MODULES),PY_TAG,PY_TAG,__file__))

def smoke_test(runtime):
    """Boot the packaged runtime in isolation: proves sqlite/ssl and shipped deps load without host libraries."""
    probe='import sqlite3,ssl,ctypes,zlib,bz2,lzma,hashlib,socket,json,'+','.join(REQUIRED_MODULES)
    try:result=subprocess.run([str(runtime/'bin'/('python'+PY_TAG)),'-I','-c',probe],capture_output=True,text=True,timeout=120)
    except (OSError,subprocess.SubprocessError):return False,'无法执行打包后的运行时'
    return result.returncode==0,result.stderr.strip()

def main():
    ensure_interpreter()
    import importlib
    import pymupdf,docx,lxml,typing_extensions
    HERE=Path(__file__).resolve().parent
    SOURCE=HERE.parent
    DEST=HERE/'build/PinkPig.app';RES=DEST/'Contents/Resources';BIN=DEST/'Contents/MacOS'
    RES.mkdir(parents=True,exist_ok=True);BIN.mkdir(parents=True,exist_ok=True)
    backend=RES/'backend';backend.mkdir(exist_ok=True)
    for name in ['app.py','writing.py','studio.py','assets.py','figure_renderer.py','typography.py','solve.py','compare.py','project.py','outline.py','review.py','README.md','.env.example','requirements.txt']:
        shutil.copy2(SOURCE/name,backend/name)
    shutil.copytree(SOURCE/'static',backend/'static',dirs_exist_ok=True)
    shutil.copy2(HERE/'desktop_server.py',backend/'desktop_server.py')
    runtime=Path(sys.base_prefix)
    r=RES/'runtime';(r/'bin').mkdir(parents=True,exist_ok=True);(r/'lib').mkdir(exist_ok=True)
    shutil.copy2(runtime/'bin/python3.12',r/'bin/python3.12')
    shutil.copy2(runtime/'lib/libpython3.12.dylib',r/'lib/libpython3.12.dylib')
    shutil.copytree(runtime/'lib/python3.12',r/'lib/python3.12',dirs_exist_ok=True,ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip'))
    site=r/'lib/python3.12/site-packages';site.mkdir(exist_ok=True)
    for m in [pymupdf,docx,lxml]:
        src=Path(m.__file__).parent;shutil.copytree(src,site/src.name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','tests'))
        for dist in src.parent.glob({'pymupdf':'pymupdf','docx':'python_docx','lxml':'lxml'}[m.__name__]+'-*.dist-info'):
            shutil.copytree(dist,site/dist.name,dirs_exist_ok=True)
    shutil.copy2(typing_extensions.__file__,site/'typing_extensions.py')
    for src in sorted(list((Path.home()/'.codex/skills').glob('hwb-*'))+list((Path.home()/'.codex/skills').glob('hbmu-*'))):
        if src.is_dir():shutil.copytree(src,RES/'skills'/src.name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','.git'))
    for name in ('math-modeling-skill',):
        src=Path.home()/'.codex/skills'/name
        if src.is_dir():shutil.copytree(src,RES/'skills'/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','.git'))
    for name in ('pinkpig-latex-writing','mathm-latex-writing'):
        src=Path.home()/'.codex/skills'/name
        if src.is_dir():shutil.copytree(src,RES/'skills'/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','.git'))
    for name in ['matplotlib','numpy','PIL','contourpy','cycler','dateutil','fontTools','kiwisolver','packaging','pyparsing','six']:
        source=Path(importlib.import_module(name).__file__)
        if source.name=='__init__.py':
            source=source.parent;shutil.copytree(source,site/source.name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','tests'))
            for extra in [source.parent/(source.name+'.libs'),source.parent/(source.name+'.dylibs')]:
                if extra.exists():shutil.copytree(extra,site/extra.name,dirs_exist_ok=True)
        else:shutil.copy2(source,site/source.name)
    for name in ['nature-writing','nature-polishing','nature-figure','nature-shared']:
        shutil.copytree(Path.home()/'.codex/skills'/name,RES/'skills'/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','.git'))
    extra=Path(importlib.import_module('matplotlib').__file__).parent.parent/'mpl_toolkits'
    if extra.exists():shutil.copytree(extra,site/'mpl_toolkits',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','tests'))
    # Never leave a broken package behind: verify the runtime boots in isolation first.
    ok,detail=smoke_test(r)
    if not ok:
        shutil.rmtree(DEST,ignore_errors=True)
        raise SystemExit('打包完整性检查未通过，已删除产物。\n'+detail)
    if (HERE/'PinkPig.icns').exists():shutil.copy2(HERE/'PinkPig.icns',RES/'PinkPig.icns')
    info={'CFBundleIconFile':'PinkPig.icns','CFBundleName':'pinkpig','CFBundleDisplayName':'pinkpig 科研平台','CFBundleIdentifier':'local.pinkpig.desktop','CFBundleVersion':'6','CFBundleShortVersionString':'0.6.0','CFBundleExecutable':'PinkPig','CFBundlePackageType':'APPL','NSHighResolutionCapable':True,'LSMinimumSystemVersion':'13.0','LSMultipleInstancesProhibited':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
    with (DEST/'Contents/Info.plist').open('wb') as f:plistlib.dump(info,f)
    subprocess.run(['xcrun','swiftc',str(HERE/'PinkPig.swift'),'-module-cache-path',str(HERE/'module-cache'),'-o',str(BIN/'PinkPig'),'-swift-version','5','-O','-target',platform.machine()+'-apple-macosx13.0','-framework','Cocoa','-framework','WebKit'],check=True)
    subprocess.run(['codesign','--force','--deep','--sign','-',str(DEST)],check=True)
    print(DEST)

if __name__=='__main__':main()
