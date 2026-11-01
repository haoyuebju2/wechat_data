"""Read-only initialize/list probe: never calls the context-reading tool."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "local-readonly-probe", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
process = subprocess.run([str(ROOT / ".upstream-runtime/Scripts/python.exe"), "-I", "-B", str(ROOT / "upstream_local/offline_context_mcp.py")],
                         input=("\n".join(json.dumps(item) for item in requests) + "\n").encode(),
                         capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert process.returncode == 0 and len(replies) == 2
    tools = replies[1]["result"]["tools"]
    assert len(tools) == 1 and tools[0]["name"] == "read_authorized_wechat_context"
    report = {"passed": True, "tool_count": len(tools), "tool_names": [item["name"] for item in tools],
              "context_tool_called": False, "model_requests": 0}
except Exception:
    report = {"passed": False, "error": "connector_handshake_failed"}
(ROOT / "validation-output/chatgpt-mcp-handshake.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
raise SystemExit(0 if report["passed"] else 1)
