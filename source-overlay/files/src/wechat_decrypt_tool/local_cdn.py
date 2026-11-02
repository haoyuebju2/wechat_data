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
from PIL import Image,ImageOps,ImageChops,ImageStat
from .app_paths import get_data_dir
from .offline_secrets import read_secret_json,write_secret_json
from .chat_helpers import _decode_message_content,_extract_md5_from_packed_info
from .media_helpers import _prefer_local_image_resource,_save_best_image_resource,_try_find_decrypted_resource
from .local_cdn_profile import discover,remember

MAX_BYTES=25*1024*1024
_DOWNLOAD=threading.Lock()
_FAILED={}
_SETTINGS_LOCK=threading.RLock()
_CANCEL=threading.local()


class CdnRejected(ValueError):
    def __init__(self,code):
        super().__init__('cdn_rejected')
        self.code=code


def settings():
    try:
        with _SETTINGS_LOCK: value=read_secret_json(get_data_dir()/'local_cdn_settings.json')
        enabled=value.get('enabled') is True
    except Exception: value={};enabled=False
    return {'enabled':enabled,'auto_mode':value.get('auto_mode','off') if value.get('auto_mode') in {'off','all','selected'} else 'off',
            'conversations':value.get('conversations',{}) if isinstance(value.get('conversations'),dict) else {},
            'auto_since':value.get('auto_since',0),'trigger':'preview_and_configured_new_messages',
            'transport':'native_http','worker_ready':worker_ready()}


def save_settings(enabled,auto_mode=None,conversations=None):
    with _SETTINGS_LOCK:
        previous=settings()
        mode=previous['auto_mode'] if auto_mode is None else auto_mode
        selected=previous['conversations'] if conversations is None else conversations
        if mode not in {'off','all','selected'} or not isinstance(selected,dict) or len(selected)>32:
            raise ValueError('invalid_original_scope')
        if any(not re.fullmatch(r'[\w@.-]{1,160}',account) or account in {'.','..'} or not isinstance(names,list)
               or len(names)>10000 or any(not isinstance(name,str) or not 1<=len(name)<=256 for name in names)
               for account,names in selected.items()): raise ValueError('invalid_original_scope')
        active=bool(enabled) and mode!='off'
        was_active=previous['enabled'] and previous['auto_mode']!='off'
        since=int(time.time()) if active and not was_active else previous['auto_since']
        write_secret_json(get_data_dir()/'local_cdn_settings.json',{'enabled':bool(enabled),'auto_mode':mode,
                          'conversations':{account:sorted(set(names)) for account,names in selected.items()},'auto_since':since})
    from .offline_originals import AUTO_ORIGINALS
    AUTO_ORIGINALS.configuration_changed()
    return settings()


def _check_cancelled():
    allowed=getattr(_CANCEL,'allowed',None)
    if allowed is not None and not allowed(): raise ValueError('disabled')


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
            mid=attrs.get('cdnmidimgurl','')
            mid=mid if re.fullmatch(r'[0-9a-fA-F]{20,8192}',mid) else ''
            size=attrs.get('hevc_mid_size','')
            size=int(size) if re.fullmatch(r'\d{1,9}',size) and int(size)<=MAX_BYTES else 0
            return {'fileid':fileid,'mid_fileid':mid,'hevc_mid_size':size,
                    'aes':bytes.fromhex(aes),'md5':digest,'aliases':{digest,packed_md5}}
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
    _check_cancelled()
    if not worker_ready() or not settings()['enabled']: raise ValueError('worker_unavailable')
    directory=Path(os.environ['WECHAT_LOCAL_CDN_IPC']).resolve(strict=True)
    nonce=secrets.token_hex(16); request=directory/(nonce+'.request.dpapi.json'); response=directory/(nonce+'.response.dpapi.json')
    job={'capability':os.environ['WECHAT_LOCAL_CDN_CAPABILITY'],'expires':min(int(time.time()+30),int(time.time()+max(0,deadline-time.monotonic()))),
         'address':address,'allowed_addresses':profile['addresses'],'provenance':'account_matched_resident_cdndns_protobuf',
         'sequence':int(fields['seq']),'body_b64':base64.b64encode(pack(fields)).decode()}
    try:
        write_secret_json(request,job)
        while time.monotonic()<deadline:
            _check_cancelled()
            if response.is_file():
                result=read_secret_json(response)
                if result.get('ok') is not True:
                    if result.get('error_code') == 'profile_not_pinned': raise ValueError('worker_profile_refresh_required')
                    raise ValueError('cdn_transport_unavailable')
                return unpack(base64.b64decode(result['response_b64'],validate=True))
            if not settings()['enabled']: raise ValueError('disabled')
            time.sleep(.04)
        raise TimeoutError('download_timeout')
    finally:
        request.unlink(missing_ok=True);response.unlink(missing_ok=True)


def _matching_thumbnail(plain,thumbnail):
    if not thumbnail:raise ValueError('conversion_comparison')
    with Image.open(io.BytesIO(thumbnail)) as reference,Image.open(io.BytesIO(plain)) as full:
        if reference.width*reference.height>60_000_000 or full.width*full.height>60_000_000:raise ValueError('image_size')
        reference=ImageOps.exif_transpose(reference).convert('RGB')
        full=ImageOps.exif_transpose(full).convert('RGB')
        ratio=(full.width/full.height)/(reference.width/reference.height)
        if not .97<=ratio<=1.03 or full.width<reference.width or full.height<reference.height:raise ValueError('conversion_comparison')
        score=ImageStat.Stat(ImageChops.difference(reference.resize((64,64)),full.resize((64,64))))
        if sum(score.mean)/3>12:raise ValueError('conversion_comparison')


def _proof_path(account_dir,md5):
    return account_dir/'_local_cdn_proofs'/(md5+'.dpapi.json')


def _cached_result(account_dir,md5,path,meta):
    if not path:return None
    data=path.read_bytes()
    try:
        proof=read_secret_json(_proof_path(account_dir,md5))
        if (proof.get('message_md5')==meta['md5'] and proof.get('fileid_sha256')==hashlib.sha256(meta['fileid'].encode()).hexdigest()
            and proof.get('preview_sha256')==hashlib.sha256(data).hexdigest()
            and proof.get('quality') in {'original','standard','converted'}):
            return _success('local',proof)
    except Exception:pass
    if hashlib.md5(data).hexdigest()==meta['md5']:
        return {'ok':True,'status':'local','message':'正在显示本机图片','quality':'local'}
    return None


def _success(status,info):
    quality=info['quality'];size=str(info['width'])+'×'+str(info['height'])
    message={'original':'已获取原图 · '+size,'standard':'已获取清晰图 · '+size+'（非原图文件）',
             'converted':'已获取清晰转换图 · '+size+'（非原图文件）'}[quality]
    return {'ok':True,'status':status,'message':message,'quality':quality,'width':info['width'],'height':info['height']}


def _save_proof(account_dir,md5,meta,data,info,saved,source=None):
    if not isinstance(saved,Path) or saved.read_bytes()!=data:return
    proof=dict(info,message_md5=meta['md5'],fileid_sha256=hashlib.sha256(meta['fileid'].encode()).hexdigest(),
               preview_sha256=hashlib.sha256(data).hexdigest())
    if source is not None:
        # Retain the exact, message-MD5-verified source without an opaque codec.
        write_secret_json(account_dir/'_local_cdn_sources'/(md5+'.dpapi.json'),{'source_b64':base64.b64encode(source).decode(),'md5':meta['md5']})
        proof['source_md5']=hashlib.md5(source).hexdigest()
    write_secret_json(_proof_path(account_dir,md5),proof)


def _download(meta,profile,address,deadline,filetype=1,picture_format=1,*,verified_source=None,thumbnail=None):
    encrypted=bytearray();total=None;flags={}
    for sequence in range(1,402):
        _check_cancelled()
        if time.monotonic()>=deadline: raise TimeoutError('download_timeout')
        start=len(encrypted)
        fields={'ver':profile['version'],'weixinnum':profile['uin'],'seq':sequence,'clientversion':profile['clientversion'],
            'clientostype':profile['clientostype'],'authkey':profile['auth_key'],'nettype':1,'acceptdupack':1,'safeproto':1,
            'filetype':filetype,'wxchattype':0,'lastretcode':0,'ipseq':0,'largesvideo':0,'sourceflag':0,'wxautostart':0,
            'downpicformat':picture_format,'rangestart':start,'rangeend':start+65535,'wxmsgflag':b'','fileid':meta['fileid']}
        reply=_exchange(profile,address,fields,deadline)
        code=int(reply.get('retcode',b'-1'))
        if code!=0:raise CdnRejected(code)
        for name in ('rsppicformat','istrans','substituteftype'):
            if name in reply:
                value=int(reply[name])
                if name in flags and flags[name]!=value:raise ValueError('format_integrity')
                flags[name]=value
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
    if len(plain)>MAX_BYTES:raise ValueError('image_integrity')
    matches=hashlib.md5(plain).hexdigest()==meta['md5']
    if matches and plain.startswith(b'wxgf'):
        if filetype!=2 or picture_format!=2 or len(plain)!=meta.get('hevc_mid_size') or flags.get('rsppicformat')!=2:
            raise ValueError('source_integrity')
        return plain,{'quality':'wxgf_source'}
    quality='original' if filetype==1 else 'standard'
    if not matches:
        # A transformed JPEG is a separate representation, never an original.
        # Require the exact WXGF source to have passed the local message MD5,
        # plus known transform flags and a bounded local-thumbnail comparison.
        if (filetype!=2 or picture_format!=1 or not verified_source or not verified_source.startswith(b'wxgf')
            or len(verified_source)!=meta.get('hevc_mid_size') or hashlib.md5(verified_source).hexdigest()!=meta['md5']
            or flags!={'rsppicformat':1,'istrans':999,'substituteftype':2}):raise ValueError('image_integrity')
        _matching_thumbnail(plain,thumbnail)
        quality='converted'
    with Image.open(io.BytesIO(plain)) as image:
        if image.width*image.height>60_000_000: raise ValueError('image_size')
        width,height=image.size
        image.verify()
    return plain,{'quality':quality,'width':width,'height':height}


def original(account_dir,server_id,username,resource_md5='',*,allowed=None):
    if not settings()['enabled']: return {'ok':False,'status':'disabled','message':'自动获取原图已关闭'}
    if not worker_ready(): return {'ok':False,'status':'unavailable','message':'原图下载组件未启动，请重新启动程序'}
    key=(str(account_dir),int(server_id),username)
    if not _DOWNLOAD.acquire(blocking=False):
        # An automatic job may already have cached this picture while another
        # image is downloading. Do not hold its preview behind the whole queue.
        try:
            meta=descriptor(account_dir,int(server_id),username)
            if resource_md5 and resource_md5.lower() not in meta['aliases']:raise ValueError('resource_mismatch')
            digest=resource_md5.lower() if resource_md5 else meta['md5']
            cached=_try_find_decrypted_resource(account_dir,digest)
            result=_cached_result(account_dir,digest,cached,meta)
            if result:return result
        except Exception:pass
        return {'ok':False,'status':'busy','message':'正在下载原图，请稍候…'}
    _CANCEL.allowed=allowed
    try:
        _check_cancelled()
        meta=descriptor(account_dir,int(server_id),username)
        if resource_md5 and resource_md5.lower() not in meta['aliases']: raise ValueError('resource_mismatch')
        md5=resource_md5.lower() if re.fullmatch(r'[0-9a-fA-F]{32}',resource_md5 or '') else meta['md5']
        local=_prefer_local_image_resource(account_dir,md5,username=username)
        result=_cached_result(account_dir,md5,local,meta)
        if result:
            _FAILED.pop(key,None)
            return result
        failed=_FAILED.get(key)
        if failed and time.monotonic()-failed[0]<30:
            return dict(failed[1],retry_after=max(1,int(30-(time.monotonic()-failed[0]))))
        thumbnail=local.read_bytes() if local and local.stat().st_size<=MAX_BYTES else None
        deadline=time.monotonic()+75
        refresh=False;last_error=None
        for fresh in (False,True):
            if fresh and (not refresh or time.monotonic()+5>=deadline): break
            for profile in discover(account_dir,force=fresh):
                for address in profile['addresses'][:2]:
                    try:
                        source=None
                        try:plain,info=_download(meta,profile,address,deadline)
                        except CdnRejected as error:
                            if error.code!=-5103017 or not meta['mid_fileid']:raise
                            middle=dict(meta,fileid=meta['mid_fileid'])
                            plain,info=_download(middle,profile,address,deadline,2,2)
                            if info['quality']=='wxgf_source':
                                source=plain
                                plain,info=_download(middle,profile,address,deadline,2,1,verified_source=source,thumbnail=thumbnail)
                        saved=_save_best_image_resource(account_dir,md5,plain)
                        _save_proof(account_dir,md5,meta,plain,info,saved,source)
                        remember(account_dir,[profile])
                        _FAILED.pop(key,None)
                        return _success('downloaded',info)
                    except (ValueError,OSError,TimeoutError) as error:
                        _check_cancelled()
                        last_error=error
                        refresh=(refresh or isinstance(error,CdnRejected) and error.code!=-5103017
                                 or str(error) in {'cdn_transport_unavailable','worker_profile_refresh_required'})
                        if time.monotonic()>=deadline: break
                if time.monotonic()>=deadline: break
        raise last_error or ValueError('original_unavailable')
    except Exception as error:
        if allowed is not None and not allowed():
            return {'ok':False,'status':'cancelled','message':'已停止自动获取原图'}
        if isinstance(error,CdnRejected) and error.code==-5103017:
            message='微信节点暂未提供这张图的可用版本，继续显示本地图片'
            reason='node_resource_unavailable'
        elif str(error) in {'image_integrity','source_integrity','conversion_comparison','format_integrity'}:
            message='清晰图片校验未通过，继续显示本地图片'
            reason='integrity_failed'
        elif str(error)=='worker_profile_refresh_required':
            message='微信下载会话尚未载入，请重新打开本工具后重试'
            reason='session_not_loaded'
        elif str(error)=='cdn_transport_unavailable':
            message='暂时无法连接微信下载节点，继续显示本地图片；可稍后重试'
            reason='transport_unavailable'
        elif str(error)=='cdn_bootstrap_unavailable':
            message='未取得当前微信下载会话，请确认微信已登录后重试'
            reason='session_unavailable'
        elif str(error) in {'missing_download_metadata','message_not_found','invalid_message'}:
            message='这条消息缺少可验证的下载信息，继续显示本地图片'
            reason='message_metadata_missing'
        else:
            message='图片获取未完成，继续显示本地图片；可稍后重试'
            reason='unavailable'
        failure={'ok':False,'status':'unavailable','message':message,'reason':reason}
        if len(_FAILED)>256: _FAILED.clear()
        _FAILED[key]=(time.monotonic(),failure)
        return failure
    finally:
        _CANCEL.allowed=None
        _DOWNLOAD.release()
