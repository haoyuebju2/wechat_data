"""ChatGPT/Codex local connector. No sockets, child processes or DB reads."""
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent
os.environ["WECHAT_TOOL_DATA_DIR"] = str(REPO)
os.environ["WECHAT_TOOL_OUTPUT_DIR"] = str(REPO / "output")
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO / "src"))
from wechat_decrypt_tool.offline_policy import install
install()
sys.path.insert(0, str(REPO.parent))
from offline_wechat.security import restrict_child_processes
restrict_child_processes()
from wechat_decrypt_tool.offline_context_protocol import serve

if __name__ == "__main__":
    serve(sys.stdin.buffer, sys.stdout.buffer)
