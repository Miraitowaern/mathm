"""Build a local macOS app from a relocatable Python 3.12 distribution."""
from pathlib import Path
import importlib,importlib.metadata,os,platform,plistlib,shutil,subprocess,sys
HERE=Path(__file__).resolve().parent
PROJECT=HERE.parent

def main():
    if sys.platform!='darwin' or sys.version_info[:2]!=(3,12):raise SystemExit('Requires macOS and Python 3.12.')
    runtime=Path(sys.base_prefix)
    required=[runtime/'bin/python3.12',runtime/'lib/libpython3.12.dylib',runtime/'lib/python3.12']
    if not all(p.exists() for p in required):raise SystemExit('Requires a relocatable Python layout: bin/python3.12 and lib/libpython3.12.dylib. See docs/desktop.md.')
    destination=HERE/'build/MathM.app'
    if destination.exists():raise SystemExit('Build directory exists. Move it aside before rebuilding to avoid mixing old resources.')
    res=destination/'Contents/Resources';binary=destination/'Contents/MacOS';backend=res/'backend'
    backend.mkdir(parents=True);binary.mkdir(parents=True)
    for name in ['app.py','writing.py','studio.py','assets.py','figure_renderer.py','typography.py','README.md','.env.example','requirements.txt']:shutil.copy2(PROJECT/name,backend/name)
    shutil.copytree(PROJECT/'static',backend/'static')
    shutil.copy2(HERE/'desktop_server.py',backend/'desktop_server.py')
    bundled=res/'runtime';(bundled/'bin').mkdir(parents=True);(bundled/'lib').mkdir()
    shutil.copy2(required[0],bundled/'bin/python3.12');shutil.copy2(required[1],bundled/'lib/libpython3.12.dylib')
    shutil.copytree(required[2],bundled/'lib/python3.12',ignore=shutil.ignore_patterns('site-packages','__pycache__','tests','test','tkinter','idlelib','turtledemo','ensurepip'))
    site=bundled/'lib/python3.12/site-packages';site.mkdir()
    modules=['pymupdf','docx','lxml','typing_extensions','matplotlib','numpy','PIL','contourpy','cycler','dateutil','fontTools','kiwisolver','packaging','pyparsing','six']
    distributions=importlib.metadata.packages_distributions();copied=set()
    for name in modules:
        module=importlib.import_module(name);source=Path(module.__file__)
        if source.name=='__init__.py':
            source=source.parent;shutil.copytree(source,site/source.name,ignore=shutil.ignore_patterns('__pycache__','tests'))
            for extra in [source.parent/(source.name+'.libs'),source.parent/(source.name+'.dylibs')]:
                if extra.exists():shutil.copytree(extra,site/extra.name)
        else:shutil.copy2(source,site/source.name)
        for dist_name in distributions.get(name,[]):
            if dist_name in copied:continue
            copied.add(dist_name);dist=importlib.metadata.distribution(dist_name)
            for file in dist.files or []:
                # Preserve installed license and attribution metadata without private configuration.
                if file.parts and file.parts[0].endswith('.dist-info'):
                    src=Path(dist.locate_file(file));out=site/str(file)
                    if src.is_file():out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,out)
    extra=Path(importlib.import_module('matplotlib').__file__).parent.parent/'mpl_toolkits'
    if extra.exists():shutil.copytree(extra,site/'mpl_toolkits',ignore=shutil.ignore_patterns('__pycache__','tests'))
    skill_root=Path(os.environ.get('MATHM_SKILLS_DIR',str(PROJECT/'skills')))
    shutil.copytree(skill_root,res/'skills',ignore=shutil.ignore_patterns('__pycache__','.DS_Store','INSTALLATION.json'))
    info={'CFBundleName':'MathM','CFBundleDisplayName':'MathM','CFBundleIdentifier':'local.mathm.desktop','CFBundleVersion':'5','CFBundleShortVersionString':'0.5.0','CFBundleExecutable':'MathM','CFBundlePackageType':'APPL','LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'LSMultipleInstancesProhibited':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
    if (HERE/'MathM.icns').exists():shutil.copy2(HERE/'MathM.icns',res/'MathM.icns');info['CFBundleIconFile']='MathM.icns'
    with (destination/'Contents/Info.plist').open('wb') as f:plistlib.dump(info,f)
    subprocess.run(['xcrun','swiftc',str(HERE/'MathM.swift'),'-module-cache-path',str(HERE/'module-cache'),'-o',str(binary/'MathM'),'-swift-version','5','-O','-target',platform.machine()+'-apple-macosx13.0','-framework','Cocoa','-framework','WebKit'],check=True)
    subprocess.run(['codesign','--force','--deep','--sign','-',str(destination)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(destination)],check=True)
    print(destination)
if __name__=='__main__':main()
