"""Compile a standard offline installation wizard from an existing clean app."""
import argparse,hashlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build(payload,compiler,out):
    out.mkdir(parents=True,exist_ok=False)
    listing=[]
    for file in sorted(payload.rglob('*')):
        if not file.is_file():continue
        relative=file.relative_to(payload)
        if any(x in relative.parts for x in ['output','offline-profile','private','.git','node_modules']):raise ValueError('Private or development files in payload')
        key=relative.as_posix()
        stage='安装桌面程序'
        if key.startswith('resources/python/'):stage='安装本地 Python 运行环境与依赖'
        elif key.startswith('resources/backend/'):stage='安装本地聊天解析组件'
        elif key.startswith('resources/ui/'):stage='安装聊天查看界面'
        elif key.startswith('resources/cdn/'):stage='安装本地图片组件'
        elif key.startswith('resources/policy/'):stage='安装安全配置组件'
        destination='{app}' if str(relative.parent)=='.' else '{app}\\'+str(relative.parent)
        listing.append(f'Source: "{file}"; DestDir: "{destination}"; Flags: ignoreversion; BeforeInstall: SetStage(\'{stage}\')')
    files=out/'package-files.iss';files.write_text('\n'.join(listing)+'\n',encoding='utf-8-sig')
    subprocess.run([str(compiler),'/DPayload='+str(payload),'/DFileList='+str(files),'/DOutput='+str(out),str(ROOT/'scripts/OfflineSetup.iss')],check=True)
    exe=out/'WeChatDataMonitor-0.1.5-Windows-x64-Offline-Setup.exe'
    (out/'SHA256SUMS.txt').write_text(hashlib.sha256(exe.read_bytes()).hexdigest()+'  '+exe.name+'\n',encoding='ascii')
    print('Complete offline wizard ready:',exe,'bytes:',exe.stat().st_size,'files:',len(listing))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--payload',type=Path,required=True);p.add_argument('--compiler',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.payload.resolve(),a.compiler.resolve(),a.output.resolve())
