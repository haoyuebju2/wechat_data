"""Read-only, bounded CDN bootstrap discovery in the user's official WeChat.

No hooks, injected code, process writes, network calls, dumps or secret logs.
The wire format was cross-checked against MIT-licensed agent-wechat protocol
sources (bf0400a3b3cde46727e38952752642f718d7ea63); see bundled notice.
"""
import ctypes
import ipaddress
from pathlib import Path
import re
import struct
import threading
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from .image_key_memory_scan import _create_win32_api, find_wechat_pids
from .wechat_detection import _parse_mmkv_kv

_CACHE = {}
_LOCK = threading.Lock()
LAST_DIAGNOSTICS = {}


def _generation():
    import psutil
    pids=find_wechat_pids()
    return [(pid,int(psutil.Process(pid).create_time())) for pid in pids if psutil.Process(pid).ppid() not in pids]


def remember(account_dir, profiles):
    from .offline_secrets import write_secret_json
    uin,source=_identity(Path(account_dir))
    clean=[]
    for profile in profiles[:4]:
        if profile['uin']!=uin: continue
        clean.append(dict(profile,auth_key=profile['auth_key'].hex(),clientostype=profile['clientostype'].decode('ascii')))
    if not clean: raise ValueError('cache_identity')
    write_secret_json(Path(account_dir)/'_local_cdn_profile.dpapi.json',{'uin':uin,'source':str(source),
        'generation':_generation(),'created':time.time(),'profiles':clean})


def _restore(account_dir,uin,source):
    from .offline_secrets import read_secret_json
    import psutil
    try:
        value=read_secret_json(Path(account_dir)/'_local_cdn_profile.dpapi.json')
        generation=_generation()
        if not generation or value['generation']!=[list(x) for x in generation] or value['uin']!=uin or value['source']!=str(source) or not 0<=time.time()-value['created']<86400:
            return None
        if not all(_official_signature(psutil.Process(pid).exe()) for pid,_ in generation): return None
        result=[]
        for profile in value['profiles'][:4]:
            if profile['uin']!=uin or not 0<profile['version']<=100: return None
            auth=bytes.fromhex(profile['auth_key']);ostype=profile['clientostype'].encode('ascii')
            if not 16<=len(auth)<=4096 or not 1<=len(ostype)<=64: return None
            if not profile['addresses'] or len(profile['addresses'])>16 or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).version!=4 for ip in profile['addresses']): return None
            result.append(dict(profile,auth_key=auth,clientostype=ostype))
        return result or None
    except Exception: return None


def varint(data, pos=0):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data): raise ValueError('short_varint')
        byte = data[pos]; pos += 1
        value |= (byte & 127) << shift
        if byte < 128: return value, pos
    raise ValueError('long_varint')


def encode_varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128); value >>= 7
    result.append(value)
    return bytes(result)


def protobuf(data, partial=False):
    fields = {}; pos = 0
    for _ in range(96):
        if pos >= len(data): break
        try:
            tag, pos = varint(data, pos); number, wire = tag >> 3, tag & 7
            if not 1 <= number <= 64: raise ValueError('field_number')
            if wire == 0: value, pos = varint(data, pos)
            elif wire == 2:
                n, pos = varint(data, pos)
                if n > 131072 or pos + n > len(data): raise ValueError('field_size')
                value, pos = data[pos:pos+n], pos+n
            elif wire in (1, 5):
                n = 8 if wire == 1 else 4
                if pos+n > len(data): raise ValueError('short_fixed')
                value, pos = data[pos:pos+n], pos+n
            else: raise ValueError('wire')
            fields.setdefault(number, []).append(value)
        except ValueError:
            if partial: break
            raise
    if not partial and pos != len(data): raise ValueError('trailing_data')
    return fields


def profile_from_fields(fields, uin):
    try:
        version = fields[1][0]
        if not isinstance(version, int) or not 0 < version <= 100 or fields[2][0] != uin: return None
        wrapper = protobuf(fields[8][0]); auth = wrapper[2][0]
        if not isinstance(auth, bytes) or not 16 <= len(auth) <= 4096 or wrapper[1][0] != len(auth): return None
        addresses = []
        for value in fields.get(6, [])[:16]:
            address = protobuf(value)[1][0].decode('ascii'); ip = ipaddress.ip_address(address)
            if ip.version == 4 and ip.is_global and address not in addresses: addresses.append(address)
        if not addresses: return None
        return {'version': version, 'uin': uin, 'auth_key': auth, 'addresses': addresses}
    except (KeyError, ValueError, TypeError, UnicodeError, IndexError): return None


def _official_signature(path):
    # WinVerifyTrust with cache-only retrieval: certificate checking cannot
    # itself trigger a CRL/OCSP request from a system service.
    from ctypes import wintypes as w
    class GUID(ctypes.Structure):
        _fields_ = [('a',w.DWORD),('b',w.WORD),('c',w.WORD),('d',ctypes.c_ubyte*8)]
    class FILE(ctypes.Structure):
        _fields_ = [('size',w.DWORD),('path',w.LPCWSTR),('handle',w.HANDLE),('subject',ctypes.c_void_p)]
    class TRUST(ctypes.Structure):
        _fields_ = [('size',w.DWORD),('callback',ctypes.c_void_p),('sip',ctypes.c_void_p),('ui',w.DWORD),
                    ('revocation',w.DWORD),('choice',w.DWORD),('file',ctypes.POINTER(FILE)),('action',w.DWORD),
                    ('state',w.HANDLE),('url',w.LPCWSTR),('flags',w.DWORD),('context',w.DWORD),('signature',ctypes.c_void_p)]
    info = FILE(ctypes.sizeof(FILE),str(path),None,None)
    trust = TRUST(); trust.size=ctypes.sizeof(TRUST); trust.ui=2; trust.choice=1; trust.file=ctypes.pointer(info); trust.flags=0x1000
    action=GUID(0x00AAC56B,0xCD44,0x11D0,(ctypes.c_ubyte*8)(0x8C,0xC2,0,0xC0,0x4F,0xC2,0x95,0xEE))
    library=ctypes.WinDLL('wintrust',use_last_error=True)
    library.WinVerifyTrust.argtypes=[w.HWND,ctypes.POINTER(GUID),ctypes.POINTER(TRUST)]
    library.WinVerifyTrust.restype=ctypes.c_long
    if library.WinVerifyTrust(None,ctypes.byref(action),ctypes.byref(trust)) != 0: return False
    import win32api
    for language,codepage in win32api.GetFileVersionInfo(str(path),'\\VarFileInfo\\Translation'):
        company=win32api.GetFileVersionInfo(str(path),f'\\StringFileInfo\\{language:04x}{codepage:04x}\\CompanyName')
        if 'Tencent' in company or '腾讯' in company: return True
    return False


def _identity(account_dir):
    import json
    metadata=json.loads((account_dir/'_source.json').read_text(encoding='utf-8'))
    source=Path(metadata['db_storage_path']).resolve(strict=True)
    config=source.parent.parent/'all_users'/'config'/'global_config'
    raw,meta=config.read_bytes(),Path(str(config)+'.crc').read_bytes()
    n=struct.unpack_from('<I',raw)[0]
    if not 0<n<=len(raw)-4: n=struct.unpack_from('<I',meta,28)[0]
    if not 0<n<=min(len(raw)-4,2*1024*1024): raise ValueError('config_size')
    dec=Cipher(algorithms.AES(b'xwechat_crypt_ke'),modes.CFB(meta[12:28])).decryptor()
    values=_parse_mmkv_kv(dec.update(raw[4:4+n])+dec.finalize())
    username=values.get('mmkv_key_user_name',''); uin=values.get('mmkv_key_latest_login_uin')
    if not isinstance(username,str) or not username or not (source.parent.name==username or source.parent.name.startswith(username+'_')):
        raise ValueError('account_mismatch')
    if not isinstance(uin,int) or not 0<uin<=0xffffffff: raise ValueError('invalid_identity')
    return uin,source


def discover(account_dir, force=False):
    import psutil
    uin,source=_identity(Path(account_dir)); cache_key=(str(source),uin,tuple(_generation()))
    with _LOCK:
        cached=_CACHE.get(cache_key)
        if not force and cached and time.monotonic()-cached[0]<600: return cached[1]
        if not force:
            restored=_restore(account_dir,uin,source)
            if restored:
                _CACHE[cache_key]=(time.monotonic(),restored)
                return restored
        started=time.monotonic(); deadline=started+20; total=0
        api=_create_win32_api()
        if api is None: raise ValueError('platform_unavailable')
        profiles=[]; versions={}; os_types={}; trusted={}
        pids=find_wechat_pids(); pids=sorted(pids,key=lambda p:(psutil.Process(p).ppid() in pids,p))
        prefix=b'\x10'+encode_varint(uin)
        for pid in pids:
            if time.monotonic()>deadline or total>=1024*1024*1024: break
            process=psutil.Process(pid); executable=process.exe()
            if Path(executable).name.lower() not in {'weixin.exe','wechat.exe'}: continue
            if executable not in trusted: trusted[executable]=_official_signature(executable)
            if not trusted[executable]: continue
            handle=api.open_process(pid)
            if not handle: continue
            address=0
            try:
                while address<0x7fffffffffff and time.monotonic()<deadline and total<1024*1024*1024:
                    region=api.query_region(handle,address)
                    if region is None or region.base_address+region.size<=address: break
                    address=region.base_address+region.size
                    if region.state!=0x1000 or region.protect&0x101 or region.protect&255 not in {4,8,0x40,0x80}: continue
                    for offset in range(0,region.size,4*1024*1024):
                        if time.monotonic()>deadline or total>=1024*1024*1024: break
                        data=api.read_memory(handle,region.base_address+offset,min(4*1024*1024+65536,region.size-offset)); total+=len(data)
                        for m in re.finditer(rb'\x00\x00\x00\x0dclientversion\x00\x00\x00([\x01-\x10])',data):
                            value=data[m.end():m.end()+m.group(1)[0]]
                            if re.fullmatch(rb'[0-9]{8,10}',value): versions[int(value)]=versions.get(int(value),0)+1
                        for m in re.finditer(rb'\x00\x00\x00\x0cclientostype\x00\x00\x00([\x01-\x40])',data):
                            value=data[m.end():m.end()+m.group(1)[0]]
                            if re.fullmatch(rb'[A-Za-z0-9 _()./-]{1,40}',value) and sum(48<=b<=57 for b in value)<=6:
                                os_types[value]=os_types.get(value,0)+1
                        pos=data.find(prefix)
                        while pos>=0:
                            if pos>=2 and data[pos-2]==8 and 0<data[pos-1]<=100:
                                candidate=profile_from_fields(protobuf(data[pos-2:pos+8192],partial=True),uin)
                                if candidate and candidate not in profiles: profiles.append(candidate)
                            pos=data.find(prefix,pos+len(prefix))
                if profiles and versions and os_types: break
            finally: api.close_handle(handle)
        LAST_DIAGNOSTICS.update(profiles=len(profiles),versions=len(versions),os_types=len(os_types),trusted_executables=sum(trusted.values()),mib=round(total/1024/1024))
        if not profiles or not versions or not os_types: raise ValueError('cdn_bootstrap_unavailable')
        version=max(versions,key=versions.get); os_type=max(os_types,key=os_types.get)
        result=[dict(profile,clientversion=version,clientostype=os_type) for profile in profiles[:4]]
        remember(account_dir,result)
        _CACHE[cache_key]=(time.monotonic(),result)
        return result
