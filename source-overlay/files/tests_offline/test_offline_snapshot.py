"""Behavioral refresh tests use synthetic SQLite databases, never real accounts."""
import json
from pathlib import Path
import shutil
import sqlite3
import time

import pytest

from test_original_business import fixture
from wechat_decrypt_tool import offline_snapshot as snapshot


@pytest.fixture
def source(tmp_path, monkeypatch):
    helper = fixture.TestChatExportMessageTypesSemantics()
    directory = helper._prepare_account(tmp_path, account="wxid_test", username="wxid_friend")
    with sqlite3.connect(directory / "session.db") as conn:
        for name, kind in (("summary", "TEXT"), ("draft", "TEXT"), ("last_msg_type", "INTEGER"),
                           ("last_msg_sub_type", "INTEGER"), ("last_timestamp", "INTEGER")):
            conn.execute(f"ALTER TABLE SessionTable ADD COLUMN {name} {kind}")
    original = tmp_path / "source" / "message" / "message_0.db"
    original.parent.mkdir(parents=True)
    shutil.copyfile(directory / original.name, original)
    (directory / "_source.json").write_text(json.dumps({"db_storage_path": str(original.parent.parent)}), encoding="utf-8")
    monkeypatch.setenv("WECHAT_TOOL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WECHAT_TOOL_OUTPUT_DIR", raising=False)
    monkeypatch.setattr(snapshot, "get_account_keys_from_store", lambda account: {"db_key": "00" * 32})
    return original, directory


def test_committed_wal_arrives_and_unchanged_source_is_not_decrypted_again(source, monkeypatch):
    original, directory = source
    conn = sqlite3.connect(original)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE synthetic_marker(value INTEGER)")
        conn.execute("INSERT INTO synthetic_marker VALUES(12345)")
        table = conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'msg_%'").fetchone()[0]
        conn.execute(f'UPDATE "{table}" SET create_time=2000000000, sort_seq=2000000000 WHERE local_id=1')
        conn.commit()
        assert Path(str(original) + "-wal").stat().st_size > 0
        original_bytes = original.read_bytes()
        wal_bytes = Path(str(original) + "-wal").read_bytes()
        report = snapshot.refresh_account("wxid_test")
        assert report["updated"] == 1 and not report["errors"], report
        with sqlite3.connect(directory / original.name) as result:
            assert result.execute("SELECT value FROM synthetic_marker").fetchone() == (12345,)
        with sqlite3.connect(directory / "session.db") as result:
            assert result.execute("SELECT create_time FROM session_last_message WHERE username='wxid_friend'").fetchone() == (2000000000,)
        assert original.read_bytes() == original_bytes
        assert Path(str(original) + "-wal").read_bytes() == wal_bytes
        monkeypatch.setattr(snapshot.WeChatDatabaseDecryptor, "decrypt_database", lambda *args: pytest.fail("unchanged source decrypted twice"))
        assert snapshot.refresh_account("wxid_test")["updated"] == 0
    finally:
        conn.close()


def test_invalid_source_keeps_previous_snapshot_and_is_retried(source):
    original, directory = source
    previous = (directory / original.name).read_bytes()
    original.write_bytes(b"invalid encrypted source" * 4096)
    for _ in range(2):
        report = snapshot.refresh_account("wxid_test")
        assert report["updated"] == 0 and report["errors"]
        assert (directory / original.name).read_bytes() == previous
    assert not list(directory.glob(".offline-refresh-*"))


def test_hmac_warning_is_never_published(source, monkeypatch):
    original, directory = source
    original.touch()
    previous = (directory / original.name).read_bytes()
    def weak_result(self, source, output):
        Path(output).write_bytes(b"must not publish")
        self.last_result = {"diagnostic_status": "ok", "hmac_warning_pages": 1}
        return True
    monkeypatch.setattr(snapshot.WeChatDatabaseDecryptor, "decrypt_database", weak_result)
    report = snapshot.refresh_account("wxid_test")
    assert report["errors"] and report["updated"] == 0
    assert (directory / original.name).read_bytes() == previous


def test_manager_serializes_same_account_and_publishes_version(monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    def work(account, *, on_publish=None):
        entered.set()
        release.wait(3)
        on_publish()
        return {"available": True, "updated": 1, "errors": []}
    monkeypatch.setattr(snapshot, "refresh_account", work)
    manager = snapshot.SnapshotManager()
    assert manager.request("wxid_test")["running"]
    assert entered.wait(1)
    assert manager.request("wxid_test")["running"]
    release.set()
    deadline = time.monotonic() + 3
    while manager.status("wxid_test")["running"] and time.monotonic() < deadline:
        time.sleep(.01)
    assert manager.status("wxid_test")["version"] == 2


def test_refresh_routes_are_authenticated_and_validate_account(source):
    from test_offline_policy import request
    assert request("/api/offline/snapshot/status?account=wxid_test", token=False).status_code == 403
    assert request("/api/offline/snapshot/status?account=../private").status_code == 400
    assert request("/api/offline/snapshot/refresh", method="POST", data={"account": "../private"}).status_code == 400
    assert request("/api/offline/snapshot/status?account=wxid_test").json()["available"]
    assert request("/api/offline/snapshot/events?account=wxid_test", token=False).status_code == 403
    assert request("/api/offline/snapshot/events?account=../private").status_code == 400


def test_native_directory_event_reaches_snapshot_without_manual_refresh(source, monkeypatch):
    import threading
    from wechat_decrypt_tool.offline_file_watch import LocalChangeNotification
    original, directory = source
    # Arm the real Windows notification before the synthetic source change.
    notification = LocalChangeNotification(original.parent.parent)
    try:
        original.touch()
        assert notification.wait(500)
    finally:
        notification.close()
    manager = snapshot.SnapshotManager()
    manager.start()
    try:
        deadline = time.monotonic() + 5
        while (manager.status("wxid_test").get("checked_at") is None or manager.status("wxid_test")["running"]) and time.monotonic() < deadline:
            time.sleep(.01)
        previous = manager.status("wxid_test")["version"]
        idle_checked_at = manager.status("wxid_test")["checked_at"]
        time.sleep(1.25)
        assert manager.status("wxid_test")["checked_at"] == idle_checked_at, "Idle source started a redundant refresh job"
        conn = sqlite3.connect(original)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE live_test(value INTEGER)")
            conn.execute("INSERT INTO live_test VALUES(321)")
            started = time.perf_counter()
            conn.commit()
            deadline = time.monotonic() + 5
            while manager.status("wxid_test")["version"] == previous and time.monotonic() < deadline:
                time.sleep(.005)
            elapsed = time.perf_counter() - started
            assert manager.status("wxid_test")["version"] > previous
            with sqlite3.connect(directory / original.name) as result:
                assert result.execute("SELECT value FROM live_test").fetchone() == (321,)
            assert elapsed < 2, f"Synthetic publication took {elapsed:.3f}s"
        finally:
            conn.close()
    finally:
        manager.stop()
        deadline = time.monotonic() + 3
        while manager.status("wxid_test")["running"] and time.monotonic() < deadline:
            time.sleep(.01)


def test_status_wait_notifies_before_cache_work_finishes(monkeypatch):
    import threading
    published, finish = threading.Event(), threading.Event()
    def work(account, *, on_publish=None):
        on_publish()
        published.set()
        finish.wait(2)
        return {"updated": 1, "cache_rebuilt": True, "errors": []}
    monkeypatch.setattr(snapshot, "refresh_account", work)
    manager = snapshot.SnapshotManager()
    try:
        manager.request("wxid_test")
        assert published.wait(1)
        status = manager.status("wxid_test")
        assert status["running"] and status["version"] == 1
        assert "published_at" in status
    finally:
        finish.set()
        manager.stop()
