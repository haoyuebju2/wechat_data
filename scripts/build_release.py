"""Build only explicitly audited public files; never package a working folder."""
import argparse,hashlib,io,json,os,subprocess,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from audit_publication import audit
ROOT=Path(__file__).resolve().parents[1]
def build(destination,development=False):
    report=audit(transport=True)
    version=json.loads((ROOT/'VERSION.json').read_text(encoding='utf8'))['version']
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    files=json.loads((ROOT/'validation-output/publication-tree.json').read_text(encoding='utf8'))
    if not development:
        for entry in files:
            tracked=subprocess.check_output(['git','show',commit+':'+entry['path']],cwd=ROOT).decode().replace('\r\n','\n')
            if tracked!=entry['content']:raise ValueError('Release sources differ from commit: '+entry['path'])
    destination.mkdir(parents=True,exist_ok=False)
    hashes={};buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for entry in files:
            data=entry['content'].encode();hashes[entry['path']]=hashlib.sha256(data).hexdigest()
            info=zipfile.ZipInfo(entry['path'],(2026,11,2,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            archive.writestr(info,data)
    payload=buffer.getvalue();source=destination/f'WeChatDataMonitor-{version}-ReviewedSources.zip';source.write_bytes(payload)
    manifest={'version':version,'source_commit':commit,'development':development,'payload_sha256':hashlib.sha256(payload).hexdigest(),'files':hashes}
    record=destination/'payload-manifest.json';record.write_text(json.dumps(manifest,sort_keys=True),encoding='utf8')
    binary=destination/f'WeChatDataMonitor-{version}-Windows-x64-Setup.exe'
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    result=subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+','/r:System.Windows.Forms.dll','/r:System.Web.Extensions.dll','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll',f'/resource:{source},release-payload.zip',f'/resource:{record},release-manifest.json',f'/out:{binary}',str(ROOT/'scripts/ReleaseInstaller.cs')],capture_output=True)
    if result.returncode:raise RuntimeError(result.stdout.decode('utf8','replace'))
    notes=destination/'RELEASE_NOTES.md';notes.write_bytes((ROOT/'docs/RELEASE_0.1.0.md').read_bytes())
    assets=[binary,source,notes]
    (destination/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in assets),encoding='ascii')
    (destination/'BUILD_INFO.json').write_text(json.dumps({k:v for k,v in manifest.items() if k!='files'},indent=2),encoding='utf8')
    print(json.dumps({'version':version,'source_commit':commit,'source_files':report['files'],'private_markers_checked':report['private_markers_checked'],'installer_bytes':binary.stat().st_size,'development':development}))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--development',action='store_true');args=parser.parse_args();build(args.output.resolve(),args.development)
