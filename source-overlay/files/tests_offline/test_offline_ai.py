import io
import json
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest
from wechat_decrypt_tool import offline_ai as ai
from wechat_decrypt_tool import offline_policy as policy
from wechat_decrypt_tool.offline_context_protocol import dispatch, serve

@pytest.fixture
def output(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_TOOL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WECHAT_TOOL_OUTPUT_DIR", raising=False)
    return tmp_path / "output"

def test_local_model_is_disabled_and_key_never_returned(output):
    assert ai.public_settings()["enabled"] is False
    with pytest.raises(ValueError, match="disabled"):
        ai.local_completion([{"role": "user", "content": "synthetic"}])
    result = ai.save_settings(True, "http://localhost:11434/v1", "synthetic-model", "synthetic-secret-do-not-print")
    assert result["base_url"] == "http://127.0.0.1:11434/v1"
    assert "api_key" not in result and result["key_present"]
    assert "synthetic-secret-do-not-print" not in (output / "ai_settings.json").read_text()
    ai.save_settings(True, "http://127.0.0.1:1234/v1", "synthetic-model")
    assert ai.public_settings()["key_present"] is False

@pytest.mark.parametrize("url", ["https://api.example.invalid/v1", "http://192.168.1.1:1234/v1",
    "http://example.invalid:1234/v1", "http://127.0.0.1:10392/v1", "http://user:secret@127.0.0.1:1234/v1",
    "http://127.0.0.1:1234/v1?remote=https://invalid", "http://127.0.0.1:1234/other", "http://127.0.0.1:80/v1"])
def test_arbitrary_model_endpoints_rejected(url):
    with pytest.raises(ValueError): ai.validate_endpoint(url)

def test_local_model_real_http_payload_and_redirect_refusal(output, monkeypatch):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            if len(received) == 2:
                self.send_response(302); self.send_header("Location", "https://invalid.example/sink"); self.end_headers(); return
            content = json.dumps({"choices": [{"message": {"content": "synthetic local answer"}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)
    # Permit only fixture binding to an ephemeral loopback port, then restore the
    # real policy before any model request is made.
    old = policy._backend_port
    monkeypatch.setattr(policy, "_backend_port", 0)
    server = HTTPServer(("127.0.0.1", 0), Handler)
    monkeypatch.setattr(policy, "_backend_port", old)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        port = server.server_address[1]
        ai.save_settings(True, f"http://127.0.0.1:{port}/v1", "fixture")
        messages = [{"role": "user", "content": "explicit synthetic preview"}]
        assert ai.local_completion(messages) == "synthetic local answer"
        assert received[0][0] == "/v1/chat/completions"
        assert received[0][1]["messages"] == messages and "tools" not in received[0][1]
        with pytest.raises(ValueError, match="request_failed"): ai.local_completion(messages)
        assert len(received) == 2
        assert policy._local_model_target.get() is None
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

def test_connection_capability_is_scoped_to_thread_and_exact_target():
    assert policy._local_model_target.get() is None
    with policy.local_model_connection("127.0.0.1", 11434):
        assert policy._local_model_target.get() == ("127.0.0.1", 11434)
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(policy._local_model_target.get).result() is None
    assert policy._local_model_target.get() is None
    with pytest.raises(policy.OfflinePolicyError):
        with policy.local_model_connection("192.168.1.1", 11434): pass

def test_grant_requires_preview_and_cloud_ack_and_is_encrypted(output):
    assert not ai.grant_status()["active"]
    with pytest.raises(ValueError): ai.create_grant("synthetic preview", False)
    ai.create_grant("synthetic preview", True)
    assert "synthetic preview" not in (output / "chatgpt_context_grant.json").read_text()
    assert ai.consume_grant() == "synthetic preview"
    with pytest.raises(ValueError): ai.consume_grant()
    assert not ai.grant_status()["active"]

def test_revoke_and_expiry_prevent_reading(output, monkeypatch):
    ai.create_grant("synthetic revoked", True); ai.revoke_grant()
    with pytest.raises(ValueError): ai.consume_grant()
    ai.create_grant("synthetic expired", True)
    now = time.time()
    monkeypatch.setattr(ai.time, "time", lambda: now + 700)
    with pytest.raises(ValueError): ai.consume_grant()

def test_concurrent_consumers_release_content_only_once(output):
    ai.create_grant("synthetic one-use", True)
    def consume():
        try: return ai.consume_grant()
        except ValueError: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))
    assert results.count("synthetic one-use") == 1

def test_mcp_protocol_only_lists_one_tool_and_cannot_read_arbitrary_files(output):
    tools = dispatch({"id": 1, "method": "tools/list"})["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["read_authorized_wechat_context"]
    ai.create_grant("synthetic authorized only", True)
    denied = dispatch({"id": 2, "method": "tools/call", "params": {"name": tools[0]["name"], "arguments": {"path": "account_keys.json"}}})
    assert denied["result"]["isError"] and ai.grant_status()["active"]
    lines = [json.dumps({"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}),
             json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
             json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": tools[0]["name"], "arguments": {}}})]
    destination = io.BytesIO()
    serve(io.BytesIO(("\n".join(lines) + "\n").encode()), destination)
    responses = [json.loads(line) for line in destination.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[1]["result"]["content"][0]["text"] == "synthetic authorized only"
    assert not ai.grant_status()["active"]

def test_ai_http_auth_and_errors_do_not_echo_input(output):
    from test_offline_policy import request
    assert request("/api/offline/ai/settings", token=False).status_code == 403
    assert request("/api/offline/ai/settings").json()["enabled"] is False
    denied = request("/api/offline/ai/grant", method="POST", data={"text": "synthetic-private-text", "cloud_ack": False})
    assert denied.status_code == 400 and "synthetic-private-text" not in denied.text
