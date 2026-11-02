"""New-image queue fed exclusively by published, verified local snapshots.

The private journal contains only local message identifiers, never image keys,
CDN credentials, message bodies or media. No network calls or native binaries.
"""
import hashlib
import base64
import json
import math
from contextlib import closing,contextmanager
from pathlib import Path
import re
import sqlite3
import threading
import time

from .app_paths import get_output_databases_dir
from . import local_cdn


def in_scope(config,account,username):
    return bool(config['enabled'] and (config['auto_mode']=='all' or
                config['auto_mode']=='selected' and username in config['conversations'].get(account,[])))


class AutoOriginals:
    def __init__(self):
        self._condition=threading.Condition()
        self._pending=set()
        self._stop=threading.Event()
        self._threads=[]
        self._known=set()
        self._signatures={}
        self._history_revision=0

    def _accounts(self):
        root=get_output_databases_dir()
        if not root.is_dir():return []
        return [p for p in root.iterdir() if p.is_dir() and re.fullmatch(r'[\w@.-]{1,160}',p.name)
                and (p/'_source.json').is_file()]

    @contextmanager
    def _journal(self,account):
        conn=sqlite3.connect(account/'_original_downloads.sqlite',timeout=2)
        conn.execute('PRAGMA busy_timeout=2000')
        conn.execute('CREATE TABLE IF NOT EXISTS cursors(db TEXT,tbl TEXT,position INTEGER,PRIMARY KEY(db,tbl))')
        conn.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,username TEXT,sid TEXT,md5 TEXT DEFAULT '',received REAL,attempts INTEGER DEFAULT 0,due REAL,status TEXT)")
        conn.execute('CREATE INDEX IF NOT EXISTS pending_jobs ON jobs(status,due)')
        conn.execute('CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT UNIQUE,username TEXT,outcome TEXT,finished REAL,attempts INTEGER)')
        conn.execute('CREATE INDEX IF NOT EXISTS history_finished ON history(finished DESC,seq DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS history_outcome ON history(outcome,seq)')
        conn.execute('CREATE TABLE IF NOT EXISTS history_meta(key TEXT PRIMARY KEY,value INTEGER)')
        try:
            with conn:
                if not conn.execute("SELECT 1 FROM history_meta WHERE key='initialized'").fetchone():
                    # Old 'done' rows do not distinguish a download from a cache
                    # hit. Import them as old completions, never as new images.
                    claimed=conn.execute("INSERT OR IGNORE INTO history_meta VALUES('initialized',1)").rowcount
                    if claimed:
                        conn.execute("INSERT OR IGNORE INTO history(job_id,username,outcome,finished,attempts) SELECT id,username,CASE WHEN status='done' THEN 'completed' ELSE status END,due,attempts FROM jobs WHERE status IN ('done','failed','cancelled')")
                        maximum=conn.execute('SELECT coalesce(max(seq),0) FROM history').fetchone()[0]
                        conn.execute("INSERT OR REPLACE INTO history_meta VALUES('seen_through',?)",(maximum,))
                yield conn
        finally:conn.close()

    def notify(self,account):
        if not self._threads or self._stop.is_set():return
        with self._condition:
            self._pending.add(account)
            self._condition.notify_all()

    def configuration_changed(self):
        for account in self._accounts():self.notify(account.name)
        with self._condition:self._condition.notify_all()

    def scan(self,account):
        """Indexed local-id deltas; never decrypt or read the live WeChat DB here."""
        config=local_cdn.settings();more=False
        with self._journal(account) as journal:
            capacity=10000-journal.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0]
            for path in sorted(account.glob('message_*.db')):
                if not re.fullmatch(r'message_\d+\.db',path.name):continue
                related=[path,account/'contact.db',account/'session.db']
                signature=tuple((p.stat().st_mtime_ns,p.stat().st_size) if p.is_file() else None for p in related)
                key=(str(account),path.name)
                if self._signatures.get(key)==signature:continue
                blocked=False;remaining=False
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1)) as source:
                    source.execute('PRAGMA query_only=ON')
                    tables={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    names={}
                    for mapping in ('Name2Id','ChatName2Id'):
                        if mapping in tables:
                            for (name,) in source.execute('SELECT user_name FROM "'+mapping+'"'):
                                if isinstance(name,str):names[hashlib.md5(name.encode()).hexdigest()]=name
                    # Contacts and sessions also cover group names missing from sender maps.
                    for filename,table,column in (('contact.db','contact','username'),('session.db','SessionTable','username')):
                        auxiliary=account/filename
                        if not auxiliary.is_file():continue
                        try:
                            with closing(sqlite3.connect(auxiliary.as_uri()+'?mode=ro',uri=True,timeout=1)) as contacts:
                                for (name,) in contacts.execute('SELECT '+column+' FROM '+table):
                                    if isinstance(name,str):names[hashlib.md5(name.encode()).hexdigest()]=name
                        except sqlite3.Error:pass
                    for table in tables:
                        if not re.fullmatch(r'Msg_[0-9a-f]{32}',table,re.I):continue
                        previous=journal.execute('SELECT position FROM cursors WHERE db=? AND tbl=?',(path.name,table)).fetchone()
                        if previous is None:
                            # On first enable skip old history; newly created conversations
                            # still include all messages dated after activation.
                            cutoff=float(config.get('auto_since') or time.time())
                            position=source.execute('SELECT coalesce(max(local_id),0) FROM "'+table+'" WHERE create_time<?',(cutoff,)).fetchone()[0]
                        else:position=previous[0]
                        before=position
                        columns={r[1] for r in source.execute('PRAGMA table_info("'+table+'")')}
                        packed='packed_info_data' if 'packed_info_data' in columns else 'NULL'
                        rows=source.execute('SELECT local_id,server_id,local_type,'+packed+',create_time FROM "'+table+'" WHERE local_id>? ORDER BY local_id LIMIT 200',(position,)).fetchall()
                        username=names.get(table[4:].lower(),'')
                        for local_id,sid,kind,info,created in rows:
                            eligible=kind==3 and sid and created>=float(config.get('auto_since') or time.time())
                            if eligible and not username and config['enabled'] and config['auto_mode']!='off':blocked=True;break
                            if eligible and username and in_scope(config,account.name,username):
                                if capacity<=0:more=True;remaining=True;break
                                identity=hashlib.sha256((path.name+':'+table+':'+str(local_id)+':'+str(sid)).encode()).hexdigest()
                                digest=local_cdn._extract_md5_from_packed_info(info)
                                cursor=journal.execute("INSERT OR IGNORE INTO jobs(id,username,sid,md5,received,due,status) VALUES(?,?,?,?,?,?, 'pending')",(identity,username,str(sid),digest,time.time(),time.time()))
                                capacity-=cursor.rowcount
                            position=local_id
                        journal.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(path.name,table,position))
                        remaining=remaining or len(rows)==200 and position>before
                    more=more or remaining
                if not blocked and not remaining:self._signatures[key]=signature
        if more and capacity>0:self.notify(account.name)
        with self._condition:self._condition.notify_all()

    def process_one(self,account):
        config=local_cdn.settings()
        if not config['enabled'] or config['auto_mode']=='off':return False
        with self._journal(account) as journal:
            row=journal.execute("SELECT id,username,sid,md5,attempts,received FROM jobs WHERE status='pending' AND due<=? ORDER BY due LIMIT 1",(time.time(),)).fetchone()
        if not row:return False
        identity,username,sid,digest,attempts,received=row
        def allowed():
            current=local_cdn.settings()
            return in_scope(current,account.name,username) and received>=current.get('auto_since',0) and not self._stop.is_set()
        if not allowed():result={'status':'excluded'}
        else:
            try:result=local_cdn.original(account,int(sid),username,digest,allowed=allowed)
            except Exception:result={'status':'unavailable'}
        status=result.get('status')
        if status in {'downloaded','local'}:state='done';due=time.time()
        elif status=='excluded' or not allowed():state='cancelled';due=time.time()
        elif status=='busy':state='pending';due=time.time()+1
        else:
            attempts+=1;state='failed' if attempts>=3 else 'pending';due=time.time()+(30 if attempts==1 else 120)
        with self._journal(account) as journal:
            journal.execute('UPDATE jobs SET status=?,attempts=?,due=? WHERE id=?',(state,attempts,due,identity))
            if state in {'done','failed','cancelled'}:
                outcome=status if state=='done' else state
                tries=attempts+1 if state=='done' else attempts
                journal.execute('INSERT OR IGNORE INTO history(job_id,username,outcome,finished,attempts) VALUES(?,?,?,?,?)',
                                (identity,username,outcome,time.time(),tries))
            journal.execute("DELETE FROM jobs WHERE status IN ('done','cancelled','failed') AND due<?",(time.time()-7*86400,))
        if state in {'done','cancelled','failed'}:
            self._history_changed()
            self.notify(account.name)
        return True

    def _history_changed(self):
        with self._condition:
            self._history_revision+=1
            self._condition.notify_all()

    def history_revision(self):
        with self._condition:return self._history_revision

    def wait_history(self,revision,timeout=10):
        with self._condition:
            self._condition.wait_for(lambda:self._stop.is_set() or self._history_revision!=revision,timeout)
            return self._history_revision

    def history_summary(self):
        counts={'downloaded':0,'local':0,'failed':0,'completed':0,'cancelled':0,'unread':0,'total':0}
        for account in self._accounts():
            if not (account/'_original_downloads.sqlite').is_file():continue
            with self._journal(account) as journal:
                seen=journal.execute("SELECT value FROM history_meta WHERE key='seen_through'").fetchone()[0]
                for outcome,count in journal.execute('SELECT outcome,count(*) FROM history GROUP BY outcome'):
                    if outcome in counts:counts[outcome]+=count
                    counts['total']+=count
                counts['unread']+=journal.execute("SELECT count(*) FROM history WHERE outcome='downloaded' AND seq>?",(seen,)).fetchone()[0]
        return counts

    @staticmethod
    def _conversation_names(account,usernames):
        names={name:name for name in usernames}
        database=account/'contact.db'
        if database.is_file() and names:
            try:
                with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=1)) as source:
                    params=','.join('?' for _ in names)
                    for username,remark,nickname in source.execute('SELECT username,remark,nick_name FROM contact WHERE username IN ('+params+')',list(names)):
                        names[username]=next((v.strip() for v in (remark,nickname,username) if isinstance(v,str) and v.strip()),username)
            except sqlite3.Error:pass
        return names

    def history(self,limit=50,cursor=None):
        boundary=None
        if cursor:
            try:
                boundary=json.loads(base64.urlsafe_b64decode(cursor+'==='))
                if (not isinstance(boundary,list) or len(boundary)!=3 or not isinstance(boundary[0],(int,float))
                    or not math.isfinite(boundary[0]) or not isinstance(boundary[1],str)
                    or not isinstance(boundary[2],int) or boundary[2]<0):raise ValueError()
            except Exception:raise ValueError('invalid_history_cursor') from None
        rows=[];through={}
        for account in self._accounts():
            if not (account/'_original_downloads.sqlite').is_file():continue
            with self._journal(account) as journal:
                through[account.name]=journal.execute('SELECT coalesce(max(seq),0) FROM history').fetchone()[0]
                clause='';params=[]
                if boundary:
                    stamp,name,seq=boundary
                    clause=' WHERE finished<? OR (finished=? AND (?<? OR (?=? AND seq<?)))'
                    params=[stamp,stamp,account.name,name,account.name,name,seq]
                records=journal.execute('SELECT seq,username,outcome,finished,attempts FROM history'+clause+' ORDER BY finished DESC,seq DESC LIMIT ?',params+[limit+1]).fetchall()
                labels=self._conversation_names(account,{r[1] for r in records})
                rows.extend({'id':account.name+':'+str(seq),'account':account.name,'conversation':labels.get(username,username),
                             'status':outcome,'finished_at':finished,'attempts':tries,'_seq':seq}
                            for seq,username,outcome,finished,tries in records)
        rows.sort(key=lambda row:(row['finished_at'],row['account'],row['_seq']),reverse=True)
        selected=rows[:limit];next_cursor=None
        if len(rows)>limit and selected:
            last=selected[-1]
            next_cursor=base64.urlsafe_b64encode(json.dumps([last['finished_at'],last['account'],last['_seq']]).encode()).decode().rstrip('=')
        for row in selected:row.pop('_seq')
        return {'items':selected,'through':through,'next_cursor':next_cursor,'summary':self.history_summary()}

    def mark_history_seen(self,through):
        changed=False
        for account in self._accounts():
            if account.name not in through or not (account/'_original_downloads.sqlite').is_file():continue
            with self._journal(account) as journal:
                maximum=journal.execute('SELECT coalesce(max(seq),0) FROM history').fetchone()[0]
                previous=journal.execute("SELECT value FROM history_meta WHERE key='seen_through'").fetchone()[0]
                value=min(maximum,through[account.name])
                if value>previous:
                    journal.execute("UPDATE history_meta SET value=? WHERE key='seen_through'",(value,));changed=True
        if changed:self._history_changed()
        return self.history_summary()

    def clear_history(self):
        for account in self._accounts():
            if not (account/'_original_downloads.sqlite').is_file():continue
            with self._journal(account) as journal:
                maximum=journal.execute('SELECT coalesce(max(seq),0) FROM history').fetchone()[0]
                journal.execute("UPDATE history_meta SET value=max(value,?) WHERE key='seen_through'",(maximum,))
                journal.execute('DELETE FROM history')
        self._history_changed()
        return self.history_summary()

    def summary(self):
        counts={'pending':0,'done':0,'failed':0}
        for account in self._accounts():
            if not (account/'_original_downloads.sqlite').is_file():continue
            try:
                with self._journal(account) as journal:
                    for status,count in journal.execute('SELECT status,count(*) FROM jobs GROUP BY status'):
                        if status in counts:counts[status]+=count
            except sqlite3.Error:pass
        return counts

    def start(self):
        if self._threads:return
        self._stop.clear()
        def index_loop():
            while not self._stop.is_set():
                try:
                    accounts={p.name:p for p in self._accounts()}
                    with self._condition:
                        names=self._pending | (set(accounts)-self._known)
                        self._pending=set();self._known=set(accounts)
                    for name in names:
                        if name in accounts:
                            try:self.scan(accounts[name])
                            except Exception:pass
                except Exception:pass
                with self._condition:
                    if not self._pending:self._condition.wait(1)
        def download_loop():
            while not self._stop.is_set():
                worked=False
                for account in self._accounts():
                    if self._stop.is_set():break
                    try:worked=self.process_one(account) or worked
                    except Exception:pass
                if not worked:
                    with self._condition:self._condition.wait(1)
        self._threads=[threading.Thread(target=loop,daemon=True,name=name) for loop,name in
                       ((index_loop,'offline-image-index'),(download_loop,'offline-image-download'))]
        for thread in self._threads:thread.start()

    def stop(self):
        self._stop.set()
        with self._condition:self._condition.notify_all()
        for thread in self._threads:thread.join(timeout=2)


AUTO_ORIGINALS=AutoOriginals()
