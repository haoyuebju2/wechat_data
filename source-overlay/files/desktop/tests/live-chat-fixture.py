"""Synthetic-only backend for the hidden desktop end-to-end test."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import site
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "upstream_local"
site.addsitedir(str(ROOT / ".upstream-runtime/Lib/site-packages"))
sys.path.insert(0, str(REPO / "src"))
directory = Path(os.environ["WECHAT_SYNTHETIC_DATA_DIR"])
os.environ["WECHAT_TOOL_DATA_DIR"] = str(directory)
os.environ["WECHAT_TOOL_OUTPUT_DIR"] = str(directory / "output")
spec = importlib.util.spec_from_file_location("synthetic_fixture", REPO / "tests/test_chat_export_message_types_semantics.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
account = fixture.TestChatExportMessageTypesSemantics()._prepare_account(directory, account="wxid_live_test", username="wxid_live_friend")
with sqlite3.connect(account / "session.db") as conn:
    for name, kind in (("summary", "TEXT"), ("draft", "TEXT"), ("last_msg_type", "INTEGER"),
                       ("last_msg_sub_type", "INTEGER"), ("last_timestamp", "INTEGER"), ("unread_count", "INTEGER")):
        conn.execute(f"ALTER TABLE SessionTable ADD COLUMN {name} {kind}")
source = directory / "synthetic_source/message/message_0.db"
source.parent.mkdir(parents=True)
shutil.copyfile(account / source.name, source)
(account / "_source.json").write_text(json.dumps({"db_storage_path": str(source.parent.parent)}), encoding="utf-8")
from wechat_decrypt_tool.key_store import upsert_account_keys_in_store
upsert_account_keys_in_store("wxid_live_test", db_key="00" * 32)
from wechat_decrypt_tool.api import app
from fastapi.routing import APIRoute
import uvicorn

connection = sqlite3.connect(source, check_same_thread=False)
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("PRAGMA wal_autocheckpoint=0")
streams = 0

@app.middleware("http")
async def count_fixture_streams(request, call_next):
    global streams
    if request.url.path == "/api/offline/snapshot/events":
        streams += 1
    return await call_next(request)

def commit():
    table = "msg_" + hashlib.md5(b"wxid_live_friend").hexdigest()
    now = int(time.time())
    connection.execute(f'INSERT INTO "{table}" (local_id,server_id,local_type,sort_seq,real_sender_id,create_time,message_content,compress_content) VALUES(?,?,?,?,?,?,?,?)',
                       (10000, 10000, 1, now * 1000, 1, now, "SYNTHETIC_LIVE_MESSAGE_20261101", None))
    connection.commit()
    return {"commit_epoch_ms": time.time() * 1000, "event_stream_requests": streams}

app.router.routes.insert(0, APIRoute("/api/offline-test/commit", commit, methods=["POST"]))
try:
    uvicorn.run(app, host="127.0.0.1", port=10392, access_log=False, log_config=None, log_level="critical")
finally:
    connection.close()
