"""Real SQLite + SQLCipher page/WAL fixtures, no diagnostic mocking."""
import importlib.util
from pathlib import Path
import sqlite3
import struct

import pytest

from wechat_decrypt_tool.offline_incremental import AuthenticatedPages
from wechat_decrypt_tool.offline_snapshot import fingerprint
from wechat_decrypt_tool.sqlite_wal import _checksum
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

spec = importlib.util.spec_from_file_location("cipher_fixture", Path(__file__).resolve().parents[1] / "tests/test_wechat_decrypt_key_modes.py")
cipher_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cipher_fixture)
KEY = bytes.fromhex("1234567890abcdef" * 4)
SALT = bytes.fromhex("ab" * 16)


def plain_database(value):
    first, second = bytearray(4096), bytearray(4096)
    first[:16] = b"SQLite format 3\0"
    first[16:24] = bytes.fromhex("1000010150402020")
    for offset, number in ((24, 1), (28, 2), (40, 1), (44, 4), (56, 1), (92, 1), (96, 3050004)):
        first[offset:offset + 4] = number.to_bytes(4, "big")
    sql = b"CREATE TABLE live(value INTEGER)"
    record = bytes([6, 23, 21, 21, 1, 13 + 2 * len(sql)]) + b"tablelivelive\x02" + sql
    for page, header, payload in ((first, 100, record), (second, 0, bytes([2, 4]) + value.to_bytes(4, "big"))):
        cell = bytes([len(payload), 1]) + payload
        offset = 4016 - len(cell)
        page[header] = 13
        page[header + 3:header + 5] = b"\0\x01"
        page[header + 5:header + 7] = offset.to_bytes(2, "big")
        page[header + 8:header + 10] = offset.to_bytes(2, "big")
        page[offset:4016] = cell
    return bytes(first + second)


def encrypted_database(value):
    plain = plain_database(value)
    return b"".join(cipher_fixture._encrypt_page(KEY, plain[index * 4096:(index + 1) * 4096], index + 1,
                                                SALT, bytes([index + 1]) * 16) for index in range(2))


def encrypted_wal(value):
    header = struct.pack(">IIII", 0x377f0682, 3007000, 4096, 0) + b"12345678"
    state = _checksum(header, "<")
    header += struct.pack(">II", *state)
    frame = struct.pack(">II", 2, 2) + b"12345678"
    page = cipher_fixture._encrypt_page(KEY, plain_database(value)[4096:], 2, SALT, b"z" * 16)
    state = _checksum(page, "<", _checksum(frame[:8], "<", state))
    return header + frame + struct.pack(">II", *state) + page


@pytest.fixture
def baseline(tmp_path):
    source, staged = tmp_path / "source.db", tmp_path / "baseline.db"
    source.write_bytes(encrypted_database(2000000000))
    decryptor = WeChatDatabaseDecryptor(KEY.hex(), capture_cipher_snapshot=True)
    assert decryptor.decrypt_database(str(source), str(staged)), decryptor.last_result.get("diagnostic_status")
    pages = AuthenticatedPages()
    pages.put(source, pages.capture(KEY.hex(), decryptor.offline_cipher_snapshot, staged, decryptor.last_result))
    return source, staged, pages


def test_authenticated_wal_page_increment_matches_full_decrypt(baseline, tmp_path):
    source, previous, pages = baseline
    wal = Path(str(source) + "-wal")
    wal.write_bytes(encrypted_wal(2000000001))
    staged = tmp_path / "incremental.db"
    entry, changed = pages.prepare(source, staged, KEY.hex(), fingerprint)
    assert changed == 1
    with sqlite3.connect(staged) as conn:
        assert conn.execute("SELECT value FROM live").fetchone() == (2000000001,)
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    full = tmp_path / "full.db"
    decryptor = WeChatDatabaseDecryptor(KEY.hex())
    assert decryptor.decrypt_database(str(source), str(full))
    assert full.read_bytes() == staged.read_bytes()
    assert previous.read_bytes() != staged.read_bytes()
    pages.put(source, entry)
    # A checkpoint of the same committed pages must not publish stale/duplicate data.
    source.write_bytes(encrypted_database(2000000001)[:4096] + encrypted_wal(2000000001)[56:])
    wal.unlink()
    assert pages.prepare(source, tmp_path / "unchanged.db", KEY.hex(), fingerprint)[1] == 0


def test_tampered_changed_page_cannot_replace_the_authenticated_cache(baseline, tmp_path):
    source, previous, pages = baseline
    old = pages.get(source)
    previous_bytes = previous.read_bytes()
    damaged = bytearray(source.read_bytes())
    damaged[5000] ^= 1
    source.write_bytes(damaged)
    destination = tmp_path / "must-not-publish.db"
    with pytest.raises(ValueError, match="hmac"):
        pages.prepare(source, destination, KEY.hex(), fingerprint)
    assert pages.get(source) is old
    assert previous.read_bytes() == previous_bytes
    assert not destination.exists()


def test_same_snapshot_reuses_authentication_without_rewriting(baseline, tmp_path):
    source, _, pages = baseline
    destination = tmp_path / "unused.db"
    _, changed = pages.prepare(source, destination, KEY.hex(), fingerprint)
    assert changed == 0 and not destination.exists()
