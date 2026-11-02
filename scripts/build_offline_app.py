"""Build a complete application from clean, already provisioned components."""
import argparse,hashlib,json,os,shutil,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION='0.1.5'
def copytree(source,target):
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','wechat_offline_source.pth'))
def build(out,prepared,stage_only=False):
    out.mkdir(parents=True,exist_ok=False)
    app=out/'electron-app';app.mkdir();(app/'src').mkdir()
    for name in ['offline-main.cjs','offline-session.cjs','offline-position.cjs','preload.cjs','renderer-startup.cjs']:
        shutil.copyfile(ROOT/'upstream_local/desktop/src'/name,app/'src'/name)
    (app/'package.json').write_text(json.dumps({'name':'wechat-data-monitor','productName':'WeChatDataMonitor','version':VERSION,'main':'src/offline-main.cjs','description':'Local WeChat data viewer','author':'haoyuebju2','license':'SEE LICENSE IN THIRD_PARTY_NOTICES.md'}),encoding='utf8')
    assets=out/'assets';assets.mkdir()
    copytree(prepared/'.runtime',assets/'python')
    target=assets/'python/Lib/site-packages';target.mkdir(exist_ok=True)
    for item in (prepared/'.upstream-runtime/Lib/site-packages').iterdir():
        if item.name in {'__pycache__','wechat_offline_source.pth'}:continue
        if item.is_dir():
            if (target/item.name).exists():shutil.copytree(item,target/item.name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            else:copytree(item,target/item.name)
        elif item.suffix!='.pyc':shutil.copyfile(item,target/item.name)
    backend=assets/'backend';backend.mkdir();copytree(ROOT/'upstream_local/src',backend/'src')
    for name in ['offline_backend.py','offline_context_mcp.py']:shutil.copyfile(ROOT/'upstream_local'/name,backend/name)
    (assets/'offline_wechat').mkdir()
    for name in ['__init__.py','security.py']:shutil.copyfile(ROOT/'offline_wechat'/name,assets/'offline_wechat'/name)
    copytree(ROOT/'upstream_local/frontend/.output/public',assets/'ui')
    cdn=assets/'cdn';cdn.mkdir();source=ROOT/'upstream_local/desktop/src/LocalCdnWorker.cs';shutil.copyfile(source,cdn/source.name)
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/target:exe','/platform:x64','/optimize+','/r:System.Web.Extensions.dll','/r:System.Security.dll','/out:'+str(cdn/'LocalCdnWorker.exe'),str(source)],check=True)
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    (cdn/'artifact.json').write_text(json.dumps({'format':'local-cdn-worker/1','source_sha256':digest(source),'binary_sha256':digest(cdn/'LocalCdnWorker.exe')}),encoding='utf8')
    shutil.copyfile(ROOT/'upstream_local/desktop/src/LICENSE-local-cdn.txt',cdn/'LICENSE-local-cdn.txt')
    policy=assets/'policy';policy.mkdir();shutil.copyfile(ROOT/'scripts/Packaged-Firewall.ps1',policy/'Packaged-Firewall.ps1')
    notices=assets/'notices';notices.mkdir()
    for name in ['THIRD_PARTY_NOTICES.md','LICENSE.md']:shutil.copyfile(ROOT/name,notices/name)
    original=ROOT/'upstream_local/THIRD_PARTY_NOTICES.md'
    if original.exists():shutil.copyfile(original,notices/'UPSTREAM_THIRD_PARTY_NOTICES.md')
    program=out/'application'
    distribution=prepared/'upstream_local/desktop/node_modules/electron/dist'
    for file in distribution.rglob('*'):
        if not file.is_file() or file.name=='default_app.asar':continue
        relative=file.relative_to(distribution)
        if relative.as_posix()=='electron.exe':relative=Path('WeChatDataMonitor.exe')
        target=program/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,target)
    (program/'resources').mkdir(exist_ok=True)
    # ASAR contains the application, not a command launcher. The Electron
    # executable loads it directly using the standard packaged-app layout.
    module=subprocess.check_output(['node','-e',"console.log(require.resolve('@electron/asar',{paths:[process.argv[1]]}))",str(ROOT/'upstream_local/desktop/node_modules')],text=True).strip()
    subprocess.run(['node','-e',"require(process.argv[1]).createPackage(process.argv[2],process.argv[3]).catch(e=>{console.error(e.message);process.exitCode=1})",module,str(app),str(program/'resources/app.asar')],check=True)
    # Copy only the component roots into their final resource paths.
    for item in assets.iterdir():
        if item.is_dir():copytree(item,program/'resources'/item.name)
    critical=['WeChatDataMonitor.exe','resources/app.asar','resources/python/python.exe','resources/python/pythonw.exe','resources/python/python314.dll','resources/policy/Packaged-Firewall.ps1','resources/cdn/LocalCdnWorker.exe']
    (program/'resources/portable-integrity.json').write_text(json.dumps({'version':VERSION,'artifacts':{name:digest(program/name) for name in critical}},indent=2),encoding='utf8')
    print(json.dumps({'application':str(program),'version':VERSION,'complete':True}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--prepared',type=Path,required=True);p.add_argument('--stage-only',action='store_true');a=p.parse_args();build(a.output.resolve(),a.prepared.resolve(),a.stage_only)
