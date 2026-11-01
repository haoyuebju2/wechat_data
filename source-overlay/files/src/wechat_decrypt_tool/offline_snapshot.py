"""Local, change-driven SQLCipher/WAL snapshots. Never loads the native broker."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

from .app_paths import get_output_databases_dir
from .key_store import get_account_keys_from_store
from .wechat_decrypt import WeChatDatabaseDecryptor
from .offline_incremental import PAGES

_FILE = re.compile(r"(?:message_\d+|message_resource|session|contact)\.db\Z")


def account_directory(account: str) -> Path:
    if not re.fullmatch(r"[\w@.-]{1,160}", account) or account in {".", ".."}:
        raise ValueError("invalid_account")
    return get_output_databases_dir() / account


def fingerprint(path: Path) -> list:
    result = []
    for suffix in ("", "-wal", "-journal"):
        try:
            stat = Path(str(path) + suffix).stat()
            result.append([stat.st_size, stat.st_mtime_ns, stat.st_ino])
        except FileNotFoundError:
            result.append(None)
    return result


def source_databases(source: Path) -> dict:
    candidates = {}
    for base in (source, source / "message", source / "session", source / "contact"):
        if not base.is_dir():
            continue
        for path in base.glob("*.db"):
            if not _FILE.fullmatch(path.name):
                continue
            if path.name in candidates:
                raise ValueError("ambiguous_source")
            candidates[path.name] = path
    return candidates


def source_signature(source: Path):
    # Metadata only. Idle reconciliation must not start refresh jobs or decrypt
    # keys/pages; unrelated source-directory changes do not need a refresh.
    return tuple((name, tuple(tuple(row) if row else None for row in fingerprint(path)))
                 for name, path in sorted(source_databases(source).items()))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".snapshot-state-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def refresh_account(account: str, *, on_publish=None) -> dict:
    """Publish each authenticated, checked file atomically; failures keep old files.

    Only message/contact/session files are refreshed: unrelated multi-GB business
    databases and local exports are untouched. The decryptor includes committed
    WAL frames and rejects a source that changed while being read.
    """
    directory = account_directory(account)
    metadata = _read_json(directory / "_source.json")
    source_value = metadata.get("db_storage_path")
    if not source_value:
        return {"available": False, "updated": 0, "errors": [], "reason": "no_local_source"}
    source = Path(source_value).resolve(strict=True)  # mandatory offline path guard
    if not source.is_dir() or source == directory.resolve():
        raise ValueError("invalid_source")
    identity = hashlib.sha256(str(source).casefold().encode()).hexdigest()
    state_path = directory / "_offline_snapshot_state.json"
    state = _read_json(state_path)
    if state.get("source") != identity:
        state = {"source": identity, "files": {}}
    records = state.setdefault("files", {})
    state_before = json.dumps(state, sort_keys=True)
    candidates = source_databases(source)
    if not candidates:
        return {"available": False, "updated": 0, "errors": [], "reason": "no_source_databases"}
    key = None
    updated = 0
    errors = []
    cache_dirty = bool(state.get("cache_dirty"))
    message_sources = [path for name, path in candidates.items() if re.fullmatch(r"message_\d+\.db", name)]
    newest = max(message_sources, key=lambda path: max(row[1] for row in fingerprint(path) if row), default=None)
    # Message pages become visible before slower contact/session/cache work.
    for name, original in sorted(candidates.items(), key=lambda item: (not bool(re.fullmatch(r"message_\d+\.db", item[0])), item[0])):
        destination = directory / name
        try:
            stamp = fingerprint(original)
            if not stamp[0]:
                continue
            output_stat = destination.stat() if destination.exists() else None
            record = records.get(name, {})
            prime = original == newest and PAGES.should_prime(original)
            if record.get("input") == stamp and output_stat and not prime:
                continue
            # Existing full decrypts already include older source/WAL files.
            if not record and output_stat and not prime and max(row[1] for row in stamp if row) <= output_stat.st_mtime_ns:
                records[name] = {"input": stamp, "output_mtime_ns": output_stat.st_mtime_ns}
                continue
            if key is None:
                key = get_account_keys_from_store(account).get("db_key", "")
            if not key:
                errors.append({"file": name, "code": "missing_local_key"})
                continue
            with tempfile.TemporaryDirectory(prefix=".offline-refresh-", dir=directory) as staging:
                staged = Path(staging) / name
                incremental = PAGES.prepare(original, staged, key, fingerprint)
                if incremental is None:
                    decryptor = WeChatDatabaseDecryptor(key, capture_cipher_snapshot=True)
                    ok = decryptor.decrypt_database(str(original), str(staged))
                    result = decryptor.last_result
                    if (not ok or result.get("failed_pages") or result.get("hmac_warning_pages")
                            or result.get("diagnostic_status") != "ok"):
                        errors.append({"file": name, "code": "snapshot_validation_failed"})
                        continue
                    entry = PAGES.capture(key, decryptor.offline_cipher_snapshot, staged, result)
                else:
                    entry, changed_pages = incremental
                    if not changed_pages:
                        records[name] = {"input": stamp, "output_mtime_ns": destination.stat().st_mtime_ns}
                        continue
                # Never replace a destination currently in a SQLite transaction.
                if any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
                    errors.append({"file": name, "code": "snapshot_busy"})
                    continue
                os.replace(staged, destination)
                PAGES.put(original, entry)
            records[name] = {"input": stamp, "output_mtime_ns": destination.stat().st_mtime_ns}
            updated += 1
            cache_dirty = True
            if on_publish is not None:
                on_publish()
        except Exception:
            # No exception strings: they may contain private paths or key material.
            errors.append({"file": name, "code": "local_refresh_failed"})
    cache_rebuilt = False
    if cache_dirty:
        try:
            from .session_last_message import build_session_last_message_table
            report = build_session_last_message_table(directory, rebuild=True)
            if report.get("status") != "success" or report.get("skippedDbs"):
                raise ValueError("cache_incomplete")
            cache_dirty = False
            cache_rebuilt = True
            if "session.db" in records:
                records["session.db"]["output_mtime_ns"] = (directory / "session.db").stat().st_mtime_ns
        except Exception:
            errors.append({"file": "session.db", "code": "preview_refresh_failed"})
    state["cache_dirty"] = cache_dirty
    if json.dumps(state, sort_keys=True) != state_before:
        _write_state(state_path, state)
    return {"available": True, "updated": updated, "errors": errors, "cache_rebuilt": cache_rebuilt}


class SnapshotManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._status = {}
        self._pending = set()
        self._watchers = {}
        self.instance = secrets.token_hex(8)
        self._stop = threading.Event()
        self._thread = None

    def status(self, account: str) -> dict:
        directory = account_directory(account)
        with self._lock:
            return dict(self._status.get(account, {"running": False, "version": 0, "revision": 0,
                         "instance": self.instance, "mode": "local-watch",
                         "available": (directory / "_source.json").is_file()}))

    def _notify(self, account):
        self._status[account]["revision"] = self._status[account].get("revision", 0) + 1
        self._condition.notify_all()

    def wait_status(self, account, revision, timeout=10):
        with self._condition:
            self._condition.wait_for(lambda: self._stop.is_set() or self.status(account)["revision"] != revision, timeout)
            return self.status(account)

    def request(self, account: str) -> dict:
        account_directory(account)
        with self._lock:
            status = self.status(account)
            if self._stop.is_set():
                return status
            if status.get("running"):
                self._pending.add(account)
                return status
            status.update(running=True, started_at=time.time())
            self._status[account] = status
            self._notify(account)
        threading.Thread(target=self._refresh, args=(account,), daemon=True,
                         name="offline-snapshot").start()
        return dict(status)

    def _refresh(self, account: str):
        def published():
            with self._condition:
                self._status[account]["version"] += 1
                self._status[account]["published_at"] = time.time()
                self._notify(account)
        while True:
            with self._lock:
                self._pending.discard(account)
            started = time.perf_counter()
            try:
                result = refresh_account(account, on_publish=published)
            except Exception:
                result = {"errors": [{"code": "local_source_unavailable"}], "updated": 0}
            with self._condition:
                status = self._status[account]
                version = status.get("version", 0) + int(bool(result.get("cache_rebuilt")))
                again = account in self._pending and not self._stop.is_set()
                status.update(result, running=again, checked_at=time.time(), version=version,
                              duration_ms=round((time.perf_counter() - started) * 1000, 1))
                self._notify(account)
            if not again:
                return

    def _watch(self, account, source, stopped):
        from .offline_file_watch import LocalChangeNotification
        notification = None
        try:
            notification = LocalChangeNotification(source)
        except Exception:
            pass  # one-second reconciliation remains available
        try:
            previous_signature = source_signature(source)
        except Exception:
            previous_signature = None
        self.request(account)
        reconcile_at = time.monotonic() + 1
        try:
            while not self._stop.is_set() and not stopped.is_set():
                try:
                    changed = notification.wait(100) if notification else False
                except Exception:
                    notification.close()
                    notification = None
                    changed = False
                if notification is None:
                    stopped.wait(.1)
                if changed or time.monotonic() >= reconcile_at:
                    if changed:
                        # Short bounded coalescing window, not a polling interval.
                        stopped.wait(.05)
                    try:
                        current_signature = source_signature(source)
                    except Exception:
                        current_signature = None
                    if current_signature != previous_signature or self.status(account).get("errors"):
                        previous_signature = current_signature
                        self.request(account)
                    reconcile_at = time.monotonic() + 1
        finally:
            if notification is not None:
                notification.close()

    def _discover(self):
        active = set()
        try:
            directories = list(get_output_databases_dir().iterdir())
        except OSError:
            directories = []
        for directory in directories:
            if not directory.is_dir():
                continue
            source_value = _read_json(directory / "_source.json").get("db_storage_path")
            if not source_value:
                continue
            account = directory.name
            active.add(account)
            previous = self._watchers.get(account)
            if previous and previous[0] == source_value and previous[2].is_alive():
                continue
            if previous:
                previous[1].set()
            stopped = threading.Event()
            thread = threading.Thread(target=self._watch, args=(account, Path(source_value), stopped),
                                      daemon=True, name="offline-source-watch")
            self._watchers[account] = (source_value, stopped, thread)
            thread.start()
        for account in set(self._watchers) - active:
            self._watchers.pop(account)[1].set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        def loop():
            while not self._stop.is_set():
                try:
                    self._discover()
                except Exception:
                    pass
                self._stop.wait(1)
        self._thread = threading.Thread(target=loop, daemon=True, name="offline-snapshot-watch")
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        for _, stopped, _ in list(self._watchers.values()):
            stopped.set()

    @property
    def stopped(self):
        return self._stop.is_set()


SNAPSHOTS = SnapshotManager()
