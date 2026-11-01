"""Register only this connector, checking all unrelated TOML data is preserved."""
import json
import os
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
name = "wechat_local_context"
config = Path(os.environ.get("CODEX_HOME") or (Path(os.environ["USERPROFILE"]) / ".codex")) / "config.toml"
cli = Path(os.environ["APPDATA"]) / "npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
python = ROOT / ".upstream-runtime/Scripts/python.exe"
entry = ROOT / "upstream_local/offline_context_mcp.py"
before = tomllib.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
expected = {"command": str(python), "args": ["-I", "-B", str(entry)]}
existing = before.get("mcp_servers", {}).get(name)
if existing is not None and any(existing.get(key) != value for key, value in expected.items()):
    raise SystemExit("Existing connector differs; no configuration changed.")
if existing is None:
    result = subprocess.run([str(cli), "mcp", "add", name, "--", expected["command"], *expected["args"]],
                            capture_output=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise SystemExit("Local connector registration failed; no credentials printed.")
after = tomllib.loads(config.read_text(encoding="utf-8"))
registered = after.get("mcp_servers", {}).get(name, {})
assert all(registered.get(key) == value for key, value in expected.items())
for value in (before, after):
    value.get("mcp_servers", {}).pop(name, None)
    if not value.get("mcp_servers"): value.pop("mcp_servers", None)
if before != after:
    raise SystemExit("Connector added, but unrelated configuration changed; review required.")
print(json.dumps({"registered": True, "name": name, "unrelated_configuration_preserved": True}))
