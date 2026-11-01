"""Synthetic inputs only. These tests never inspect a real WeChat account."""
import asyncio
import ctypes
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ["WECHAT_TOOL_OFFLINE_TOKEN"] = "synthetic-test-token-" + "0" * 48
os.environ["WECHAT_TOOL_PORT"] = "10392"
sys.path.insert(0, str(ROOT / "src"))

from wechat_decrypt_tool.offline_policy import OfflinePolicyError, OfflineAccessMiddleware
from wechat_decrypt_tool.api import app
import httpx


def request(path, *, token=True, host="127.0.0.1:10392", origin=None, method="GET", data=None):
    async def run():
        headers = {}
        if token:
            headers["X-Offline-Token"] = os.environ["WECHAT_TOOL_OFFLINE_TOKEN"]
        if origin is not None:
            headers["Origin"] = origin
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 23232))
        async with httpx.AsyncClient(transport=transport, base_url="http://"+host) as client:
            return await client.request(method, path, headers=headers, json=data)
    return asyncio.run(run())


def test_authenticated_health_and_response_policy():
    response = request("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert "connect-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("kwargs", [{"token":False}, {"host":"evil.invalid:10392"}, {"origin":"https://evil.invalid"}])
def test_cross_origin_host_and_unauthenticated_rejected(kwargs):
    assert request("/api/health", **kwargs).status_code == 403


@pytest.mark.parametrize("target", [("198.51.100.1",443),("127.0.0.1",18888),("::1",18888)])
def test_tcp_and_other_local_services_blocked(target):
    family = socket.AF_INET6 if ":" in target[0] else socket.AF_INET
    with socket.socket(family) as connection, pytest.raises(OfflinePolicyError):
        connection.connect(target)


def test_udp_blocked_before_sending():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as connection, pytest.raises(OfflinePolicyError):
        connection.sendto(b"synthetic-not-private",("198.51.100.1",53))


def test_dns_blocked():
    with pytest.raises(OfflinePolicyError):
        socket.getaddrinfo("example.invalid",443)


def test_subprocess_blocked():
    with pytest.raises(OfflinePolicyError):
        subprocess.Popen([sys.executable,"-c","pass"])


def test_opaque_native_modules_blocked():
    with pytest.raises(ImportError):
        importlib.import_module("wx_key")
    with pytest.raises(OfflinePolicyError):
        ctypes.CDLL(str(ROOT/"src/wechat_decrypt_tool/native/img_helper.dll"))


def test_network_files_blocked():
    with pytest.raises(OfflinePolicyError):
        open(r"\\example.invalid\share\private.db","rb")


@pytest.mark.parametrize("action", [lambda p: os.stat(p), lambda p: Path(p).resolve(), lambda p: os.access(p,os.R_OK)])
def test_network_path_metadata_blocked_before_smb(action):
    with pytest.raises(OfflinePolicyError):
        action(r"\\example.invalid\share\private.db")


def test_remote_key_fallback_reads_no_configuration_files():
    from wechat_decrypt_tool import key_service
    with patch.object(key_service,"get_wechat_internal_global_config") as reader:
        with pytest.raises(OfflinePolicyError):
            asyncio.run(key_service.fetch_and_save_remote_keys(account="synthetic"))
        reader.assert_not_called()


def test_telemetry_no_queue_no_sender():
    from wechat_decrypt_tool import native_core_telemetry as module
    with patch.object(module,"_post_events") as sender:
        module.record_product_event("database_open")
        module.record_product_event("export_completed")
        module.shutdown_product_telemetry()
        sender.assert_not_called()


@pytest.mark.parametrize("path", ["/api/cdn/connect","/api/chat/media/emoji/download","/api/sns/video_remote", "/api/chat/media/voice/transcription/models/synthetic/download"])
def test_online_actions_fail_with_explicit_offline_status(path):
    response=request(path,method="POST" if path!="/api/sns/video_remote" else "GET",data={})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "OFFLINE_FEATURE_DISABLED"


def test_capabilities_do_not_advertise_unavailable_native_features():
    result=request("/api/system/platform").json()
    assert result["offline"] is True
    assert result["database_key_auto"] is True
    assert result["realtime_wcdb"] is False
    assert result["wechat_process_media_hook"] is False


def test_local_export_integrity_never_loads_native_module():
    from wechat_decrypt_tool.export_integrity import load_wce_integrity_native, seal_entries
    native=load_wce_integrity_native()
    entry=json.loads(native.record_bytes("messages.json",b"synthetic"))
    sealed=seal_entries("synthetic-export",[entry])
    assert sealed["authoritativeSealFormat"]=="local-sha256/1"
    assert sealed["signature"].startswith("local-sha256:")
    assert "default-src" in native.gate_style()
    assert "https://" not in native.runtime_js()


def test_local_key_signature_and_verified_candidate():
    from wechat_decrypt_tool.local_key_scan import iter_candidate_pointers,verify_candidate
    pointer=0x123456789
    pattern=pointer.to_bytes(8,"little")+bytes(8)+b"\x20"+bytes(7)+b"\x2f"+bytes(7)
    assert list(iter_candidate_pointers(b"prefix"+pattern+b"suffix"))==[pointer]
    with patch("wechat_decrypt_tool.local_key_scan._resolve_page1_key_material",side_effect=lambda key,page:(key,b"mac","raw") if key==bytes(range(32)) else None):
        assert verify_candidate(bytes(range(32)),b"synthetic",[b""])==bytes(range(32))
        assert verify_candidate(b"x"*32,b"synthetic",[b""]) is None


def test_logging_does_not_write_message_content(capsys):
    from wechat_decrypt_tool.logging_config import get_logger
    logger=get_logger("synthetic-test")
    logger.error("SYNTHETIC_PRIVATE_BODY")
    out=capsys.readouterr()
    assert "SYNTHETIC_PRIVATE_BODY" not in out.out+out.err


def test_dpapi_key_files_roundtrip_without_plaintext(tmp_path):
    from wechat_decrypt_tool.offline_secrets import write_secret_json,read_secret_json
    target=tmp_path/"synthetic-keys.json"
    value={"synthetic-account":{"db_key":"deadbeef"*8,"image_aes_key":"synthetic-key-16"}}
    write_secret_json(target,value)
    raw=target.read_text()
    assert "deadbeef" not in raw
    assert "synthetic-account" not in raw
    assert read_secret_json(target)==value
    assert not list(tmp_path.glob("*.dpapi-tmp"))
