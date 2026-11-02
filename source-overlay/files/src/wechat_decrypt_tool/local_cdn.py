"""On-preview original downloads via a narrowly scoped, separate network worker."""
import base64
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import threading
import time

from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives import padding
from PIL import Image
from .app_paths import get_data_dir
from .offline_secrets import read_secret_json,write_secret_json
from .chat_helpers import _decode_message_content,_extract_md5_from_packed_info
from .media_helpers import _prefer_local_image_resource,_save_best_image_resource
from .local_cdn_profile import discover,remember

MAX_BYTES=25*1024*1024
_DOWNLOAD=threading.Lock()
_FAILED={}


def settings():
    try:
        value=json.loads((get_data_dir()/'local_cdn_settings.json').read_text(encoding='utf-8'))
        enabled=value.get('enabled') is True
    except (OSError,ValueError,TypeError): enabled=False
    return {'enabled':enabled,'trigger':'selected_image_preview','transport':'native_http','worker_ready':worker_ready()}


def save_settings(enabled):
    path=get_data_dir()/'local_cdn_settings.json'
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'enabled':bool(enabled)}),encoding='utf-8')
    os.replace(temporary,path)
    return settings()


def worker_ready():
    token=os.environ.get('WECHAT_LOCAL_CDN_CAPABILITY',''); directory=os.environ.get('WECHAT_LOCAL_CDN_IPC','')
    if len(token)!=64 or not directory: return False
    try:
        ready=json.loads((Path(directory)/'ready.json').read_text(encoding='utf-8'))
        import psutil
        return (secrets.compare_digest(ready.get('capability_sha256',''),hashlib.sha256(token.encode()).hexdigest())
                and psutil.Process(int(ready['pid'])).name().lower()=='localcdnworker.exe')
    except Exception: return False


def descriptor(account_dir,server_id,username):
    if not username or len(username)>256 or not -2**63<=server_id<2**64 or server_id==0: raise ValueError('invalid_message')
    if server_id>=2**63: server_id-=2**64
    table='Msg_'+hashlib.md5(username.encode()).hexdigest()
    for path in sorted(account_dir.glob('message_*.db'),key=lambda p:p.stat().st_mtime,reverse=True)[:32]:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1) as connection:
            connection.execute('PRAGMA query_only=ON')
            exists=connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",(table,)).fetchone()
            if not exists: continue
            columns={item[1] for item in connection.execute('PRAGMA table_info("'+table+'")')}
            packed='packed_info_data' if 'packed_info_data' in columns else 'NULL'
            row=connection.execute('SELECT local_type,message_content,compress_content,'+packed+' FROM "'+table+'" WHERE server_id=? ORDER BY create_time DESC LIMIT 1',(server_id,)).fetchone()
            if not row or int(row[0])!=3: continue
            text=_decode_message_content(row[2],row[1])
            attrs={key:html.unescape(value) for key,value in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*[\"\x27]([^\"\x27]*)[\"\x27]',text)}
            fileid=attrs.get('cdnbigimgurl') or attrs.get('cdnmidimgurl') or ''
            aes=attrs.get('aeskey',''); digest=attrs.get('md5','').lower()
            if not re.fullmatch(r'[0-9a-fA-F]{20,8192}',fileid) or not re.fullmatch(r'[0-9a-fA-F]{32}',aes) or not re.fullmatch(r'[0-9a-f]{32}',digest):
                raise ValueError('missing_download_metadata')
            packed_md5=_extract_md5_from_packed_info(row[3]).lower()
            return {'fileid':fileid,'aes':bytes.fromhex(aes),'md5':digest,'aliases':{digest,packed_md5}}
    raise ValueError('message_not_found')


def pack(fields):
    output=bytearray()
    for key,value in sorted(fields.items()):
        key=key.encode('ascii'); value=value if isinstance(value,bytes) else str(value).encode('ascii')
        output.extend(struct.pack('>I',len(key))+key+struct.pack('>I',len(value))+value)
    if not 16<=len(output)<=65536: raise ValueError('request_size')
    return bytes(output)


def unpack(data):
    if not 0<len(data)<=2*1024*1024: raise ValueError('response_size')
    fields={}; pos=0
    while pos<len(data):
        if len(fields)>=64 or pos+4>len(data): raise ValueError('field_count')
        n=struct.unpack_from('>I',data,pos)[0];pos+=4
        if not 1<=n<=128 or pos+n+4>len(data): raise ValueError('field_name')
        key=data[pos:pos+n].decode('ascii');pos+=n
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',key) or key in fields: raise ValueError('field_name')
        n=struct.unpack_from('>I',data,pos)[0];pos+=4
        if pos+n>len(data): raise ValueError('field_value')
        fields[key]=data[pos:pos+n];pos+=n
    return fields


def _exchange(profile,address,fields,deadline):
    if not worker_ready() or not settings()['enabled']: raise ValueError('worker_unavailable')
    directory=Path(os.environ['WECHAT_LOCAL_CDN_IPC']).resolve(strict=True)
    nonce=secrets.token_hex(16); request=directory/(nonce+'.request.dpapi.json'); response=directory/(nonce+'.response.dpapi.json')
    job={'capability':os.environ['WECHAT_LOCAL_CDN_CAPABILITY'],'expires':min(int(time.time()+30),int(time.time()+max(0,deadline-time.monotonic()))),
         'address':address,'allowed_addresses':profile['addresses'],'provenance':'account_matched_resident_cdndns_protobuf',
         'sequence':int(fields['seq']),'body_b64':base64.b64encode(pack(fields)).decode()}
    try:
        write_secret_json(request,job)
        while time.monotonic()<deadline:
            if response.is_file():
                result=read_secret_json(response)
                if result.get('ok') is not True: raise ValueError('cdn_transport_unavailable')
                return unpack(base64.b64decode(result['response_b64'],validate=True))
            if not settings()['enabled']: raise ValueError('disabled')
            time.sleep(.04)
        raise TimeoutError('download_timeout')
    finally:
        request.unlink(missing_ok=True);response.unlink(missing_ok=True)


def _download(meta,profile,address,deadline):
    encrypted=bytearray();total=None
    for sequence in range(1,402):
        if time.monotonic()>=deadline: raise TimeoutError('download_timeout')
        start=len(encrypted)
        fields={'ver':profile['version'],'weixinnum':profile['uin'],'seq':sequence,'clientversion':profile['clientversion'],
            'clientostype':profile['clientostype'],'authkey':profile['auth_key'],'nettype':1,'acceptdupack':1,'safeproto':1,
            'filetype':1,'wxchattype':0,'lastretcode':0,'ipseq':0,'largesvideo':0,'sourceflag':0,'wxautostart':0,
            'downpicformat':1,'rangestart':start,'rangeend':start+65535,'wxmsgflag':b'','fileid':meta['fileid']}
        reply=_exchange(profile,address,fields,deadline)
        if int(reply.get('retcode',b'-1'))!=0: raise ValueError('cdn_rejected')
        current_total=int(reply.get('totalsize',b'0'));data=reply.get('filedata',b'')
        if not data or len(data)>65536 or int(reply.get('rangestart',b'-1'))!=start or int(reply.get('rangeend',b'-1'))!=start+len(data)-1:
            raise ValueError('range_integrity')
        if not 0<current_total<=MAX_BYTES+16 or total not in (None,current_total) or start+len(data)>current_total:
            raise ValueError('total_integrity')
        if 'seq' in reply and int(reply['seq'])!=sequence: raise ValueError('sequence_integrity')
        total=current_total;encrypted.extend(data)
        if len(encrypted)==total: break
    if total is None or len(encrypted)!=total or len(encrypted)%16: raise ValueError('incomplete_download')
    dec=Cipher(algorithms.AES(meta['aes']),modes.ECB()).decryptor();padded=dec.update(bytes(encrypted))+dec.finalize()
    unpad=padding.PKCS7(128).unpadder();plain=unpad.update(padded)+unpad.finalize()
    if len(plain)>MAX_BYTES or hashlib.md5(plain).hexdigest()!=meta['md5']: raise ValueError('image_integrity')
    with Image.open(io.BytesIO(plain)) as image:
        if image.width*image.height>60_000_000: raise ValueError('image_size')
        image.verify()
    return plain


def original(account_dir,server_id,username,resource_md5=''):
    if not settings()['enabled']: return {'ok':False,'status':'disabled','message':'自动获取原图已关闭'}
    if not worker_ready(): return {'ok':False,'status':'unavailable','message':'原图下载组件未启动，请重新启动程序'}
    key=(str(account_dir),int(server_id),username)
    if time.monotonic()-_FAILED.get(key,-1000)<30: return {'ok':False,'status':'unavailable','message':'原图暂不可用，正在显示本地图片'}
    if not _DOWNLOAD.acquire(blocking=False): return {'ok':False,'status':'busy','message':'正在获取另一张原图…'}
    try:
        meta=descriptor(account_dir,int(server_id),username)
        if resource_md5 and resource_md5.lower() not in meta['aliases']: raise ValueError('resource_mismatch')
        md5=resource_md5.lower() if re.fullmatch(r'[0-9a-fA-F]{32}',resource_md5 or '') else meta['md5']
        local=_prefer_local_image_resource(account_dir,md5,username=username)
        if local and hashlib.md5(local.read_bytes()).hexdigest()==meta['md5']:
            return {'ok':True,'status':'local','message':''}
        deadline=time.monotonic()+75
        refresh=False
        for fresh in (False,True):
            if fresh and (not refresh or time.monotonic()+5>=deadline): break
            for profile in discover(account_dir,force=fresh):
                for address in profile['addresses'][:2]:
                    try:
                        plain=_download(meta,profile,address,deadline)
                        _save_best_image_resource(account_dir,md5,plain)
                        remember(account_dir,[profile])
                        return {'ok':True,'status':'downloaded','message':'已获取原图'}
                    except (ValueError,OSError,TimeoutError) as error:
                        refresh=refresh or str(error)=='cdn_rejected'
                        if time.monotonic()>=deadline: break
                if time.monotonic()>=deadline: break
        raise ValueError('original_unavailable')
    except Exception:
        _FAILED[key]=time.monotonic()
        if len(_FAILED)>256: _FAILED.clear()
        return {'ok':False,'status':'unavailable','message':'原图暂不可用：请确认微信已登录，图片未过期；继续显示本地图片'}
    finally: _DOWNLOAD.release()
