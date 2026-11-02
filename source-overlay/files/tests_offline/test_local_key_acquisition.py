"""Fresh acquisition with synthetic memory; never reads a local key store."""
import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wechat_decrypt_tool import local_key_scan as scan
from wechat_decrypt_tool import key_service
from wechat_decrypt_tool.routers import keys


def fake_memory(monkeypatch, tmp_path):
    page = tmp_path / 'synthetic-encrypted.db'
    page.write_bytes(bytes([1]) * 4096)
    monkeypatch.setattr(key_service, '_resolve_v4_probe_db_file', lambda _: page)
    monkeypatch.setattr(key_service, '_resolve_wechat_dll_path', lambda _: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(scan, 'find_wechat_pids', lambda: (10, 20))
    monkeypatch.setattr(scan, '_enumerate_scannable_regions', lambda api, handle, **kw: [SimpleNamespace(base_address=handle * 4096, size=32)])
    text = b'0123456789abcdefghijklmnopqrstuv'
    binary = bytes(range(32))
    events = []

    class Api:
        def open_process(self, pid): events.append(('open', pid)); return pid
        def close_handle(self, handle): events.append(('close', handle))
        def read_memory(self, handle, address, size):
            if address in (0x100000, 0x200000): return text if address == 0x100000 else binary
            pointer = 0x100000 if handle == 10 else 0x200000
            return pointer.to_bytes(8, 'little') + bytes(8) + b'\x20' + bytes(7) + b'\x2f' + bytes(7)

    monkeypatch.setattr(scan, '_create_win32_api', Api)
    return text, binary, events


def test_discovers_all_processes_before_verifying_and_prioritizes_binary(monkeypatch, tmp_path):
    text, binary, events = fake_memory(monkeypatch, tmp_path)
    tried = []
    def verify(candidate, *args, **kwargs):
        assert ('close', 10) in events and ('close', 20) in events
        tried.append(candidate)
        return candidate if candidate == binary else None
    monkeypatch.setattr(scan, 'verify_candidate', verify)
    result = scan.get_local_database_key('synthetic')
    assert result['verified'] and result['db_key'] == binary.hex()
    assert tried == [binary]


def test_printable_candidate_is_still_verified_as_fallback(monkeypatch, tmp_path):
    text, binary, events = fake_memory(monkeypatch, tmp_path)
    tried = []
    def verify(candidate, *args, **kwargs):
        tried.append(candidate)
        return candidate if candidate == text else None
    monkeypatch.setattr(scan, 'verify_candidate', verify)
    assert scan.get_local_database_key('synthetic')['db_key'] == text.hex()
    assert tried == [binary, text]


def test_cancelled_discovery_does_not_verify_and_closes_process(monkeypatch, tmp_path):
    _, _, events = fake_memory(monkeypatch, tmp_path)
    cancelled = threading.Event(); cancelled.set()
    monkeypatch.setattr(scan, 'verify_candidate', lambda *a, **kw: pytest.fail('Cancelled scan verified a candidate'))
    with pytest.raises(TimeoutError): scan.get_local_database_key('synthetic', cancel_event=cancelled)
    assert events == [('open', 10), ('close', 10)]


def test_windows_route_keeps_event_loop_responsive(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(keys, 'is_macos', lambda: False)
    def worker(**kwargs):
        if not release.wait(0.5): raise TimeoutError('Event loop was blocked')
        return {'db_key': '11' * 32, 'method': 'local_source_memory_scan'}
    monkeypatch.setattr(keys, 'get_db_key_workflow', worker)
    class Request:
        async def is_disconnected(self): return False
    async def run():
        task = asyncio.create_task(keys.get_wechat_db_key(Request(), db_storage_path='synthetic', key_mode='key_v4'))
        await asyncio.sleep(0.03)
        release.set()
        result = await task
        assert result['status'] == 0
    asyncio.run(run())


def test_disconnect_cancels_scan_without_advertising_disabled_hook(monkeypatch):
    observed = []
    monkeypatch.setattr(keys, 'is_macos', lambda: False)
    def worker(cancel_event=None, **kwargs):
        observed.append(cancel_event.wait(1))
        raise TimeoutError('Stopped')
    monkeypatch.setattr(keys, 'get_db_key_workflow', worker)
    class Request:
        async def is_disconnected(self): return True
    result = asyncio.run(keys.get_wechat_db_key(Request(), db_storage_path='synthetic', key_mode='key_v4'))
    assert observed == [True] and result['status'] == -2
    assert result['data']['can_fallback_to_hook'] is False
