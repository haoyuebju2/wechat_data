"""Bounded in-memory authenticated page cache; never writes keys or ciphertext.

Unchanged ciphertext SHA-256 digests reuse only pages from a fully authenticated
snapshot. Every changed page is HMAC verified before AES decrypt. A complete
SQLite quick_check is required before atomic publication by the caller.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import threading

from .sqlite_diagnostics import collect_sqlite_diagnostics, sqlite_diagnostics_status
from .sqlite_wal import merge_wal_snapshot
from .wechat_decrypt import (PAGE_SIZE, SQLITE_HEADER, _compute_page_hmac, _decrypt_page,
                            _resolve_page1_key_material)


@dataclass(frozen=True)
class Entry:
    key_digest: bytes
    salt: bytes
    hashes: tuple
    plain: bytes


def _hashes(data):
    view = memoryview(data)
    return tuple(hashlib.sha256(view[offset:offset + PAGE_SIZE]).digest()
                 for offset in range(0, len(data), PAGE_SIZE))


class AuthenticatedPages:
    LIMIT = 384 * 1024 * 1024
    FILE_LIMIT = 256 * 1024 * 1024

    def __init__(self):
        self.lock = threading.Lock()
        self.entries = OrderedDict()

    def get(self, source):
        with self.lock:
            return self.entries.get(str(source))

    def put(self, source, entry):
        if entry is None:
            return
        with self.lock:
            self.entries[str(source)] = entry
            self.entries.move_to_end(str(source))
            while sum(len(value.plain) for value in self.entries.values()) > self.LIMIT:
                self.entries.popitem(last=False)

    def discard(self, source):
        with self.lock:
            self.entries.pop(str(source), None)

    def should_prime(self, source):
        if self.get(source) is not None or source.stat().st_size > self.FILE_LIMIT:
            return False
        with source.open("rb") as stream:
            return stream.read(16) != SQLITE_HEADER

    def capture(self, key, cipher, staged, result):
        if (cipher is None or len(cipher) > self.FILE_LIMIT or len(cipher) % PAGE_SIZE
                or result.get("index_repair", {}).get("success")):
            return None
        return Entry(hashlib.sha256(bytes.fromhex(key)).digest(), cipher[:16], _hashes(cipher), staged.read_bytes())

    def prepare(self, source, staged, key, stamp):
        entry = self.get(source)
        key_bytes = bytes.fromhex(key)
        if entry is None or entry.key_digest != hashlib.sha256(key_bytes).digest():
            return None
        before = stamp(source)
        cipher = source.read_bytes()
        try:
            wal = Path(str(source) + "-wal").read_bytes()
        except FileNotFoundError:
            wal = b""
        try:
            with Path(str(source) + "-journal").open("rb") as stream:
                if stream.read(8) == bytes.fromhex("d9d505f920a163d7"):
                    raise ValueError("pending_rollback_journal")
        except FileNotFoundError:
            pass
        if before != stamp(source):
            raise ValueError("source_changed_during_read")
        if len(cipher) > self.FILE_LIMIT or cipher[:16] != entry.salt or len(cipher) % PAGE_SIZE:
            return None
        material = _resolve_page1_key_material(key_bytes, cipher[:PAGE_SIZE])
        if material is None:
            raise ValueError("key_not_authenticated")
        enc_key, mac_key, _ = material
        verify = lambda page, number: hmac.compare_digest(page[-64:], _compute_page_hmac(mac_key, page, number))
        cipher, wal_info = merge_wal_snapshot(cipher, wal, PAGE_SIZE, verify_page=verify)
        hashes = _hashes(cipher)
        if hashes == entry.hashes:
            return entry, 0
        plain = bytearray(entry.plain[:len(cipher)])
        if len(plain) < len(cipher):
            plain.extend(b"\0" * (len(cipher) - len(plain)))
        changed = 0
        for index, digest in enumerate(hashes):
            if index < len(entry.hashes) and digest == entry.hashes[index]:
                continue
            page = cipher[index * PAGE_SIZE:(index + 1) * PAGE_SIZE]
            if not verify(page, index + 1):
                raise ValueError("changed_page_hmac_failed")
            plain[index * PAGE_SIZE:(index + 1) * PAGE_SIZE] = _decrypt_page(enc_key, page, index + 1)
            changed += 1
        plain[18:20] = b"\x01\x01"
        if wal_info["committed_frames"]:
            plain[28:32] = wal_info["database_pages"].to_bytes(4, "big")
        staged.write_bytes(plain)
        if sqlite_diagnostics_status(collect_sqlite_diagnostics(staged, quick_check=True)) != "ok":
            self.discard(source)
            raise ValueError("incremental_sqlite_check_failed")
        return Entry(entry.key_digest, entry.salt, hashes, bytes(plain)), changed


PAGES = AuthenticatedPages()
