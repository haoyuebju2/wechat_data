"""User-scoped Windows DPAPI storage; plaintext is never written by this module."""
import base64
import json
import os
from pathlib import Path

FORMAT="windows-dpapi-user/1"

def write_secret_json(path,payload):
    if os.name!="nt":
        raise RuntimeError("当前密钥存储只支持 Windows 用户级 DPAPI。")
    import win32crypt
    data=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode()
    encrypted=win32crypt.CryptProtectData(data,"WechatDataMonitor local keys",None,None,None,1)
    envelope=json.dumps({"format":FORMAT,"encrypted":base64.b64encode(encrypted).decode()},separators=(",",":"))
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+".dpapi-tmp")
    try:
        with temporary.open("x",encoding="utf-8") as stream:
            stream.write(envelope);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)

def read_secret_json(path):
    envelope=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(envelope,dict) or envelope.get("format")!=FORMAT:
        # Backward-compatible reading of an explicitly provided local archive.
        # New and updated key files are always DPAPI-protected.
        return envelope
    import win32crypt
    _,data=win32crypt.CryptUnprotectData(base64.b64decode(envelope["encrypted"],validate=True),None,None,None,1)
    return json.loads(data)
