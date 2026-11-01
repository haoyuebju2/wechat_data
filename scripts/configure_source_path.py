"""Setup helper kept as a file to avoid PowerShell 5 native quoting ambiguity."""
from pathlib import Path
import sys
import sysconfig

source = Path(sys.argv[1]).resolve(strict=True)
if not (source / "wechat_decrypt_tool/offline_policy.py").is_file():
    raise SystemExit("Reviewed offline source is missing")
Path(sysconfig.get_path("purelib"), "wechat_offline_source.pth").write_text(str(source), encoding="utf-8")
