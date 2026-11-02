"""Real SQLite history: read reset, clear isolation, migration and pagination."""
import shutil
import sqlite3
import time
from unittest.mock import Mock

import pytest
from test_offline_originals import setup,receive
from wechat_decrypt_tool import offline_originals as module,local_cdn as cdn


def completed(setup,monkeypatch,kind='downloaded',local_id=2,name='friend'):
    account,engine,config=setup
    receive(account,name,local_id)
    engine.scan(account)
    monkeypatch.setattr(cdn,'original',Mock(return_value={'status':kind}))
    assert engine.process_one(account)
    return account,engine,config


def test_read_reset_only_marks_observed_downloads_and_cache_hits_do_not_count(setup,monkeypatch):
    account,engine,_=completed(setup,monkeypatch)
    first=engine.history()
    assert first['summary']['unread']==1 and first['items'][0]['status']=='downloaded'
    completed(setup,monkeypatch,local_id=3)
    assert engine.mark_history_seen(first['through'])['unread']==1
    assert engine.history_summary()['total']==2
    revision=engine.history_revision()
    engine.mark_history_seen(first['through'])
    assert engine.history_revision()==revision, 'Duplicate acknowledgements must not start an SSE loop'
    completed(setup,monkeypatch,'local',local_id=4)
    summary=engine.history_summary()
    assert summary['downloaded']==2 and summary['local']==1 and summary['unread']==1


def test_clear_preserves_cache_jobs_and_cursor_and_new_events_survive_old_ack(setup,monkeypatch):
    account,engine,_=completed(setup,monkeypatch)
    seen=engine.history()['through']
    cached=account/'synthetic-cached-image.dat';cached.write_bytes(b'synthetic-local-media')
    with engine._journal(account) as db:
        jobs=db.execute('SELECT * FROM jobs').fetchall();cursors=db.execute('SELECT * FROM cursors').fetchall()
    assert engine.clear_history()['total']==0
    with engine._journal(account) as db:
        assert db.execute('SELECT * FROM jobs').fetchall()==jobs
        assert db.execute('SELECT * FROM cursors').fetchall()==cursors
    restarted=module.AutoOriginals();restarted.scan(account)
    assert restarted.history_summary()['total']==0
    assert cached.read_bytes()==b'synthetic-local-media'
    completed(setup,monkeypatch,local_id=3)
    assert engine.mark_history_seen(seen)['unread']==1
    assert engine.history_summary()['total']==1


def test_legacy_completions_are_imported_once_without_claiming_new_downloads(setup):
    account,engine,_=setup
    with sqlite3.connect(account/'_original_downloads.sqlite') as db:
        db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY,username TEXT,sid TEXT,md5 TEXT DEFAULT '',received REAL,attempts INTEGER DEFAULT 0,due REAL,status TEXT)")
        db.execute("INSERT INTO jobs(id,username,sid,due,status) VALUES('legacy','friend','42',?,'done')",(time.time(),))
    result=engine.history()
    assert result['items'][0]['status']=='completed'
    assert result['summary']['completed']==1 and result['summary']['downloaded']==0 and result['summary']['unread']==0
    engine.clear_history()
    assert module.AutoOriginals().history_summary()['total']==0


def test_retry_attempts_record_only_terminal_failure(setup,monkeypatch):
    account,engine,_=setup
    receive(account,'friend');engine.scan(account)
    monkeypatch.setattr(cdn,'original',Mock(return_value={'status':'unavailable'}))
    for attempt in range(1,4):
        assert engine.process_one(account)
        assert engine.history_summary()['total']==int(attempt==3)
        with engine._journal(account) as db:db.execute('UPDATE jobs SET due=0')
    result=engine.history()
    assert result['items'][0]['attempts']==3
    assert result['summary']['failed']==1 and result['summary']['unread']==0


def test_pagination_across_accounts_handles_equal_times_without_duplicates(setup,monkeypatch):
    account,engine,config=setup;config['auto_mode']='all'
    stamp=int(time.time())+5;monkeypatch.setattr(module.time,'time',lambda:stamp)
    other=account.parent/'second-account';other.mkdir()
    shutil.copyfile(account/'message_0.db',other/'message_0.db');(other/'_source.json').write_text('{}')
    for directory in (account,other):
        for name in ('friend','group@chatroom'):receive(directory,name)
        engine.scan(directory)
    monkeypatch.setattr(cdn,'original',Mock(return_value={'status':'downloaded'}))
    for directory in (account,other):
        assert engine.process_one(directory) and engine.process_one(directory)
    ids=[];cursor=None
    for _ in range(4):
        page=engine.history(1,cursor);ids.extend(row['id'] for row in page['items']);cursor=page['next_cursor']
    assert len(set(ids))==len(ids)==4 and cursor is None
    assert engine.history_summary()['unread']==4
    with pytest.raises(ValueError):engine.history(cursor='not-a-valid-cursor')


def test_history_routes_require_auth_and_validate_boundaries(setup,monkeypatch):
    _,engine,_=completed(setup,monkeypatch)
    from wechat_decrypt_tool.routers import local_cdn as router
    from test_offline_policy import request
    monkeypatch.setattr(router,'AUTO_ORIGINALS',engine)
    base='/api/offline/originals/history'
    for path,method in ((base,'GET'),(base,'DELETE'),(base+'/seen','POST'),(base+'/events','GET')):
        assert request(path,method=method,token=False,data={'through':{}}).status_code==403
    assert request(base+'?limit=101').status_code==422
    assert request(base+'?cursor=bad').status_code==400
    assert request(base+'/seen',method='POST',data={'through':{'synthetic':-1}}).status_code==400
    assert engine.history_summary()['total']==1
    assert request(base,method='DELETE').json()['total']==0


def test_converted_download_is_counted_separately_from_an_original(setup,monkeypatch):
    account,engine,_=setup
    receive(account,'friend');engine.scan(account)
    monkeypatch.setattr(cdn,'original',Mock(return_value={'status':'downloaded','quality':'converted'}))
    assert engine.process_one(account)
    result=engine.history()
    assert result['summary']['converted']==1 and result['summary']['downloaded']==0
    assert result['summary']['unread']==1 and result['items'][0]['status']=='converted'
