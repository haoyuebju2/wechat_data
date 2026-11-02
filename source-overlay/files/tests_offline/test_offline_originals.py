"""Behavioral tests: synthetic SQLite arrivals, scoped queues and real caching."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import Mock

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_decrypt_tool import local_cdn as cdn,offline_originals as module


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('WECHAT_TOOL_DATA_DIR',str(tmp_path))
    monkeypatch.delenv('WECHAT_TOOL_OUTPUT_DIR',raising=False)
    config={'enabled':True,'auto_mode':'selected','conversations':{'synthetic':['friend','group@chatroom']},'auto_since':int(time.time())}
    monkeypatch.setattr(cdn,'settings',lambda:config)
    account=tmp_path/'output'/'databases'/'synthetic';account.mkdir(parents=True)
    (account/'_source.json').write_text('{}')
    with sqlite3.connect(account/'message_0.db') as db:
        db.execute('CREATE TABLE Name2Id(user_name TEXT)')
        for name in ('friend','group@chatroom','excluded'):
            db.execute('INSERT INTO Name2Id VALUES(?)',(name,))
            table='Msg_'+hashlib.md5(name.encode()).hexdigest()
            db.execute('CREATE TABLE "'+table+'"(local_id INTEGER PRIMARY KEY,server_id INTEGER,local_type INTEGER,create_time INTEGER,packed_info_data BLOB)')
            db.execute('INSERT INTO "'+table+'" VALUES(1,100,3,1,NULL)')
    engine=module.AutoOriginals()
    monkeypatch.setattr(cdn,'_extract_md5_from_packed_info',lambda _: 'a'*32)
    return account,engine,config


def receive(account,name,local_id=2,kind=3):
    table='Msg_'+hashlib.md5(name.encode()).hexdigest()
    with sqlite3.connect(account/'message_0.db') as db:
        db.execute('INSERT INTO "'+table+'" VALUES(?,?,?,?,NULL)',(local_id,9007199254740993+local_id,kind,int(time.time())))


def test_selected_private_and_group_arrivals_skip_history_text_and_excluded(setup,monkeypatch):
    account,engine,config=setup
    engine.scan(account)
    assert engine.summary()['pending']==0
    for name in ('friend','group@chatroom','excluded'):receive(account,name)
    receive(account,'friend',3,kind=1)
    engine.scan(account)
    assert engine.summary()['pending']==2
    download=Mock(return_value={'status':'downloaded'});monkeypatch.setattr(cdn,'original',download)
    assert engine.process_one(account) and engine.process_one(account)
    assert not engine.process_one(account)
    assert {call.args[2] for call in download.call_args_list}=={'friend','group@chatroom'}
    assert all(call.args[1]==9007199254740995 and call.args[3]=='a'*32 for call in download.call_args_list)
    engine.scan(account)
    assert engine.summary()=={'pending':0,'done':2,'failed':0}


def test_all_includes_new_conversations_and_persists_cursor_and_pending(setup,monkeypatch):
    account,engine,config=setup;config['auto_mode']='all'
    engine.scan(account)
    for name in ('friend','group@chatroom','excluded'):receive(account,name)
    engine.scan(account)
    another=module.AutoOriginals();another.scan(account)
    assert another.summary()['pending']==3
    download=Mock(return_value={'status':'local'});monkeypatch.setattr(cdn,'original',download)
    for _ in range(3):assert another.process_one(account)
    assert {call.args[2] for call in download.call_args_list}=={'friend','group@chatroom','excluded'}


def test_batched_scan_does_not_lose_large_burst(setup):
    account,engine,config=setup;engine.scan(account)
    for index in range(2,407):receive(account,'friend',index)
    for _ in range(3):engine.scan(account)
    assert engine.summary()['pending']==405


def test_retry_cap_busy_and_scope_removal(setup,monkeypatch):
    account,engine,config=setup;engine.scan(account);receive(account,'friend');engine.scan(account)
    download=Mock(return_value={'status':'busy'});monkeypatch.setattr(cdn,'original',download)
    engine.process_one(account)
    with engine._journal(account) as db:
        assert db.execute('SELECT attempts FROM jobs').fetchone()[0]==0
        db.execute('UPDATE jobs SET due=0')
    download.return_value={'status':'unavailable'}
    for attempt in range(1,4):
        assert engine.process_one(account)
        with engine._journal(account) as db:
            assert db.execute('SELECT attempts FROM jobs').fetchone()[0]==attempt
            db.execute('UPDATE jobs SET due=0')
    assert engine.summary()['failed']==1 and not engine.process_one(account)
    receive(account,'friend',3);engine.scan(account)
    config['conversations']={}
    before=download.call_count
    assert engine.process_one(account)
    assert download.call_count==before and engine.summary()['pending']==0


def test_setting_change_cancels_in_progress_background_request(setup,monkeypatch):
    account,engine,config=setup;engine.scan(account);receive(account,'friend');engine.scan(account)
    def download(*args,allowed):
        assert allowed()
        config['auto_mode']='off'
        assert not allowed()
        return {'status':'unavailable'}
    monkeypatch.setattr(cdn,'original',download)
    assert engine.process_one(account)
    with engine._journal(account) as db:assert db.execute('SELECT status FROM jobs').fetchone()[0]=='cancelled'


def test_settings_persist_encrypted_scope_and_preview_toggle_preserves_it(tmp_path,monkeypatch):
    monkeypatch.setenv('WECHAT_TOOL_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(cdn,'worker_ready',lambda:False)
    # Isolate the global scheduler from this synthetic settings directory.
    monkeypatch.setattr(module.AUTO_ORIGINALS,'configuration_changed',lambda:None)
    value=cdn.save_settings(True,'selected',{'synthetic':['friend','group@chatroom']})
    assert value['auto_mode']=='selected' and value['auto_since']>0
    envelope=json.loads((tmp_path/'local_cdn_settings.json').read_text())
    assert envelope['format']=='windows-dpapi-user/1' and 'group@chatroom' not in json.dumps(envelope)
    assert cdn.save_settings(False)['conversations']==value['conversations']
    assert cdn.save_settings(True)['auto_mode']=='selected'
    with pytest.raises(ValueError):cdn.save_settings(True,'selected',{'../invalid':['friend']})


def test_scope_is_account_bound(setup):
    _,_,config=setup
    assert module.in_scope(config,'synthetic','friend')
    assert not module.in_scope(config,'different-account','friend')
    config['auto_mode']='all'
    assert module.in_scope(config,'different-account','friend')
    config['enabled']=False
    assert not module.in_scope(config,'synthetic','friend')


def test_new_group_table_created_after_enable_is_not_skipped(setup):
    account,engine,config=setup;config['auto_mode']='all';engine.scan(account)
    name='new_group@chatroom';table='Msg_'+hashlib.md5(name.encode()).hexdigest()
    with sqlite3.connect(account/'message_0.db') as db:
        db.execute('INSERT INTO Name2Id VALUES(?)',(name,))
        db.execute('CREATE TABLE "'+table+'"(local_id INTEGER PRIMARY KEY,server_id INTEGER,local_type INTEGER,create_time INTEGER)')
        db.execute('INSERT INTO "'+table+'" VALUES(1,99,3,?)',(int(time.time()),))
    engine.scan(account)
    assert engine.summary()['pending']==1


def test_unchanged_snapshots_do_not_reopen_message_databases(setup,monkeypatch):
    account,engine,config=setup;engine.scan(account)
    connect=sqlite3.connect
    def guarded(path,*args,**kwargs):
        assert 'message_0.db' not in str(path), 'Idle snapshot was scanned again'
        return connect(path,*args,**kwargs)
    monkeypatch.setattr(module.sqlite3,'connect',guarded)
    engine.scan(account)


def test_verified_wal_publication_automatically_downloads_without_opening_preview(tmp_path,monkeypatch):
    """Real directory event, snapshot decrypt, SQLite discovery and AES cache path."""
    from test_offline_snapshot import source as source_fixture
    from wechat_decrypt_tool import offline_snapshot as snapshots,media_helpers
    from PIL import Image
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
    # Use the existing synthetic account/source fixture without loading real data.
    original,account=source_fixture.__wrapped__(tmp_path,monkeypatch)
    engine=module.AutoOriginals()
    monkeypatch.setattr(module,'AUTO_ORIGINALS',engine)
    config={'enabled':True,'auto_mode':'selected','conversations':{'wxid_test':['wxid_friend']},'auto_since':int(time.time())}
    monkeypatch.setattr(cdn,'settings',lambda:config)
    monkeypatch.setattr(cdn,'worker_ready',lambda:True)
    monkeypatch.setattr(cdn,'remember',lambda *_:None)
    monkeypatch.setattr(cdn,'_prefer_local_image_resource',lambda *_a,**_kw:None)
    image=io.BytesIO();Image.new('RGB',(900,700),'blue').save(image,'JPEG')
    plain=image.getvalue()+b'synthetic appended metadata\n'*357
    digest=hashlib.md5(plain).hexdigest();key=b'0123456789abcdef'
    pad=padding.PKCS7(128).padder();padded=pad.update(plain)+pad.finalize()
    encrypt=Cipher(algorithms.AES(key),modes.ECB()).encryptor();cipher=encrypt.update(padded)+encrypt.finalize()
    profile={'version':1,'uin':1234,'auth_key':b'synthetic-auth','clientversion':1,'clientostype':b'Windows','addresses':['8.8.8.8']}
    monkeypatch.setattr(cdn,'discover',lambda *_a,**_kw:[profile])
    exchanges=[]
    def exchange(_profile,_address,fields,_deadline):
        exchanges.append(fields)
        start=fields['rangestart'];data=cipher[start:start+65536]
        return {'retcode':b'0','seq':str(fields['seq']).encode(),'totalsize':str(len(cipher)).encode(),
                'rangestart':str(start).encode(),'rangeend':str(start+len(data)-1).encode(),'filedata':data}
    monkeypatch.setattr(cdn,'_exchange',exchange)
    cdn._FAILED.clear()
    manager=snapshots.SnapshotManager()
    engine.start();manager.start()
    try:
        deadline=time.monotonic()+6
        while manager.status('wxid_test').get('checked_at') is None and time.monotonic()<deadline:time.sleep(.01)
        assert manager.status('wxid_test').get('checked_at')
        with sqlite3.connect(original) as db:
            table=db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'msg_%'").fetchone()[0]
            db.execute('PRAGMA journal_mode=WAL')
            xml=f'<msg><img cdnbigimgurl="{("ab"*80)}" aeskey="{key.hex()}" md5="{digest}" /></msg>'
            db.execute('UPDATE "'+table+'" SET local_type=3,server_id=42,message_content=?,compress_content=NULL,create_time=?,local_id=900001 WHERE local_id=1',(xml,int(time.time())))
            db.commit()
        deadline=time.monotonic()+8
        cached=None
        while time.monotonic()<deadline:
            cached=media_helpers._try_find_decrypted_resource(account,digest)
            if cached:break
            time.sleep(.02)
        assert cached and cached.read_bytes()==plain
        assert exchanges and engine.summary()['done']==1
        with Image.open(cached) as parsed:parsed.load();assert parsed.size==(900,700)
    finally:
        manager.stop();engine.stop()
