"""Private fork backend entry: no reload, no external native broker, no access logs."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from wechat_decrypt_tool.offline_policy import install
install()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from offline_wechat.security import restrict_child_processes
restrict_child_processes()

import uvicorn

if __name__ == "__main__":
    uvicorn.run("wechat_decrypt_tool.api:app", host="127.0.0.1", port=10392,
                reload=False, workers=1, access_log=False, log_config=None, log_level="critical")
