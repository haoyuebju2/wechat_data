"""Behavioral tests with synthetic SQLite messages and authenticated AES media."""
import hashlib
import io
from pathlib import Path
import sqlite3
import sys
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PIL import Image
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives import padding
import pytest
from wechat_decrypt_tool import local_cdn as cdn


@pytest.fixture
def fixture(tmp_path,monkeypatch,request):
    account=tmp_path/'synthetic';account.mkdir()
    image=io.BytesIO();Image.new('RGB',(686,343),'blue').save(image,'JPEG' if getattr(request,'param',None)=='jpeg_metadata' else 'PNG');plain=image.getvalue()
    if getattr(request,'param',None)=='jpeg_metadata':plain+=b'synthetic appended metadata\n'*357
    digest=hashlib.md5(plain).hexdigest();key=b'0123456789abcdef';username='synthetic_friend'
    table='Msg_'+hashlib.md5(username.encode()).hexdigest()
    with sqlite3.connect(account/'message_0.db') as conn:
        conn.execute('CREATE TABLE "'+table+'"(local_type INTEGER,message_content TEXT,compress_content BLOB,server_id INTEGER,create_time INTEGER)')
        xml=f'<msg><img cdnbigimgurl="{("ab"*80)}" aeskey="{key.hex()}" md5="{digest}" /></msg>'
        conn.execute('INSERT INTO "'+table+'" VALUES(3,?,NULL,42,1)',(xml,))
    pad=padding.PKCS7(128).padder();padded=pad.update(plain)+pad.finalize()
    encrypt=Cipher(algorithms.AES(key),modes.ECB()).encryptor();cipher=encrypt.update(padded)+encrypt.finalize()
    profile={'version':1,'uin':1234,'auth_key':b'synthetic-auth-material','clientversion':1,'clientostype':b'Windows','addresses':['8.8.8.8']}
    monkeypatch.setattr(cdn,'settings',lambda:{'enabled':True})
    monkeypatch.setattr(cdn,'worker_ready',lambda:True)
    monkeypatch.setattr(cdn,'discover',lambda *_a,**_k:[profile])
    monkeypatch.setattr(cdn,'remember',lambda *_:None)
    monkeypatch.setattr(cdn,'_prefer_local_image_resource',lambda *_a,**_k:None)
    cache=account/'verified.png'
    save=Mock(side_effect=lambda _a,_m,data:cache.write_bytes(data))
    monkeypatch.setattr(cdn,'_save_best_image_resource',save)
    calls=[]
    def exchange(_profile,_address,fields,_deadline):
        calls.append(fields)
        assert 'aeskey' not in fields and key not in cdn.pack(fields)
        start=fields['rangestart'];part=cipher[start:start+65536]
        return {'retcode':b'0','seq':str(fields['seq']).encode(),'rangestart':str(start).encode(),
                'rangeend':str(start+len(part)-1).encode(),'totalsize':str(len(cipher)).encode(),'filedata':part}
    monkeypatch.setattr(cdn,'_exchange',exchange)
    cdn._FAILED.clear()
    return account,username,digest,plain,cache,save,calls


def test_download_validates_message_digest_and_reuses_verified_local_file(fixture,monkeypatch):
    account,username,digest,plain,cache,save,calls=fixture
    assert cdn.original(account,42,username,digest)['status']=='downloaded'
    assert cache.read_bytes()==plain and save.call_count==1 and calls
    monkeypatch.setattr(cdn,'_prefer_local_image_resource',lambda *_a,**_k:cache)
    monkeypatch.setattr(cdn,'_exchange',lambda *_:pytest.fail('Cached original must not contact worker'))
    assert cdn.original(account,42,username,digest)['status']=='local'


def test_failed_integrity_never_replaces_local_image(fixture,monkeypatch):
    account,username,digest,plain,cache,save,calls=fixture
    original=cdn._exchange
    def tamper(*args):
        value=original(*args);value['filedata']=b'\x00'+value['filedata'][1:];return value
    monkeypatch.setattr(cdn,'_exchange',tamper)
    assert cdn.original(account,42,username,digest)['ok'] is False
    assert not cache.exists() and not save.called


def test_disabled_and_non_image_messages_cannot_trigger_download(fixture,monkeypatch):
    account,username,digest,plain,cache,save,calls=fixture
    monkeypatch.setattr(cdn,'settings',lambda:{'enabled':False})
    assert cdn.original(account,42,username,digest)['status']=='disabled'
    assert not calls
    with pytest.raises(ValueError):cdn.descriptor(account,999,username)
    with pytest.raises(ValueError):cdn.unpack(cdn.pack({'retcode':'0'})+b'\x00')


def test_other_message_resource_cannot_be_overwritten(fixture):
    account,username,digest,plain,cache,save,calls=fixture
    assert cdn.original(account,42,username,'f'*32)['ok'] is False
    assert not calls and not save.called


@pytest.mark.parametrize('fixture',['jpeg_metadata'],indirect=True)
def test_original_with_appended_metadata_reaches_real_cache_and_is_reused(fixture,monkeypatch):
    account,username,digest,plain,cache,save,calls=fixture
    from wechat_decrypt_tool import media_helpers as media
    monkeypatch.setattr(cdn,'_save_best_image_resource',media._save_best_image_resource)
    assert cdn.original(account,42,username,digest)['status']=='downloaded'
    cached=media._try_find_decrypted_resource(account,digest)
    assert cached and cached.read_bytes()==plain
    with Image.open(cached) as image:
        image.load()
        assert image.size==(686,343)
    monkeypatch.setattr(cdn,'_prefer_local_image_resource',lambda *_a,**_k:cached)
    before=len(calls)
    assert cdn.original(account,42,username,digest)['status']=='local'
    assert len(calls)==before


def test_cached_image_is_available_while_background_download_lock_is_held(fixture,monkeypatch):
    account,username,digest,plain,cache,save,calls=fixture
    cache.write_bytes(plain)
    monkeypatch.setattr(cdn,'_try_find_decrypted_resource',lambda *_:cache)
    cdn._DOWNLOAD.acquire()
    try:
        assert cdn.original(account,42,username,digest)['status']=='local'
        assert not cdn.original(account,42,username,'f'*32)['ok']
        assert not calls
    finally:cdn._DOWNLOAD.release()


def converted_fixture(fixture,monkeypatch,*,bad_source=False,bad_thumbnail=False,bad_flags=False):
    account,username,_,_,_,_,calls=fixture
    from wechat_decrypt_tool import media_helpers as media
    raw=b'wxgf'+b'synthetic source with a trusted message digest'*20
    digest=hashlib.md5(raw).hexdigest();key=b'0123456789abcdef'
    image=io.BytesIO();Image.new('RGB',(800,400),'blue').save(image,'JPEG');jpeg=image.getvalue()
    thumb=account/'thumbnail.png';Image.new('RGB',(100,50),'red' if bad_thumbnail else 'blue').save(thumb)
    table='Msg_'+hashlib.md5(username.encode()).hexdigest()
    xml=f'<msg><img cdnmidimgurl="{("ab"*80)}" aeskey="{key.hex()}" md5="{digest}" hevc_mid_size="{len(raw)}" /></msg>'
    with sqlite3.connect(account/'message_0.db') as db:db.execute('UPDATE "'+table+'" SET message_content=?',(xml,))
    monkeypatch.setattr(cdn,'_prefer_local_image_resource',lambda *_a,**_k:thumb)
    monkeypatch.setattr(cdn,'_save_best_image_resource',media._save_best_image_resource)
    calls.clear()
    def exchange(_profile,_address,fields,_deadline):
        calls.append(fields)
        if fields['filetype']==1:return {'retcode':b'-5103017'}
        is_source=fields['downpicformat']==2
        plain=(raw+b'corruption' if bad_source else raw) if is_source else jpeg
        pad=padding.PKCS7(128).padder();padded=pad.update(plain)+pad.finalize()
        encrypt=Cipher(algorithms.AES(key),modes.ECB()).encryptor();cipher=encrypt.update(padded)+encrypt.finalize()
        start=fields['rangestart'];part=cipher[start:start+65536]
        return {'retcode':b'0','seq':str(fields['seq']).encode(),'rangestart':str(start).encode(),
            'rangeend':str(start+len(part)-1).encode(),'totalsize':str(len(cipher)).encode(),'filedata':part,
            'rsppicformat':b'2' if is_source else b'1','istrans':b'0' if bad_flags else b'999',
            'substituteftype':b'12' if is_source else b'2'}
    monkeypatch.setattr(cdn,'_exchange',exchange)
    return account,username,digest,raw,jpeg,thumb,calls


def test_missing_original_verifies_wxgf_then_caches_distinct_converted_preview(fixture,monkeypatch):
    account,username,digest,raw,jpeg,thumb,calls=converted_fixture(fixture,monkeypatch)
    from wechat_decrypt_tool import media_helpers as media
    from wechat_decrypt_tool.offline_secrets import read_secret_json
    result=cdn.original(account,42,username,digest)
    assert result['ok'] and result['quality']=='converted'
    assert result['width']==800 and result['height']==400 and '非原图文件' in result['message']
    assert [c['filetype'] for c in calls]==[1,2,2]
    cached=media._try_find_decrypted_resource(account,digest)
    assert cached.read_bytes()==jpeg and hashlib.md5(jpeg).hexdigest()!=digest
    proof=read_secret_json(cdn._proof_path(account,digest))
    assert proof['source_md5']==digest and proof['preview_sha256']==hashlib.sha256(jpeg).hexdigest()
    source=read_secret_json(account/'_local_cdn_sources'/(digest+'.dpapi.json'))
    import base64
    assert base64.b64decode(source['source_b64'])==raw
    monkeypatch.setattr(cdn,'_prefer_local_image_resource',lambda *_a,**_k:cached)
    before=len(calls)
    assert cdn.original(account,42,username,digest)['quality']=='converted'
    assert len(calls)==before
    cached.write_bytes(b'changed cache')
    assert cdn._cached_result(account,digest,cached,cdn.descriptor(account,42,username)) is None


@pytest.mark.parametrize('guard',['bad_source','bad_thumbnail','bad_flags'])
def test_converted_preview_cannot_bypass_source_digest_or_image_comparison(fixture,monkeypatch,guard):
    account,username,digest,raw,jpeg,thumb,calls=converted_fixture(fixture,monkeypatch,**{guard:True})
    from wechat_decrypt_tool import media_helpers as media
    assert not cdn.original(account,42,username,digest)['ok']
    assert media._try_find_decrypted_resource(account,digest) is None
    if guard=='bad_source':assert not any(c['filetype']==2 and c['downpicformat']==1 for c in calls)


def test_original_checksum_failure_never_uses_a_lower_quality_fallback(fixture,monkeypatch):
    account,username,digest,plain,cache,save,calls=fixture
    original=cdn._exchange
    def changed(*args):
        reply=original(*args);reply['filedata']=b'\x00'+reply['filedata'][1:];return reply
    monkeypatch.setattr(cdn,'_exchange',changed)
    assert not cdn.original(account,42,username,digest)['ok']
    assert all(call['filetype']==1 for call in calls)
