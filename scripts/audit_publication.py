"""Audit the explicit public file list without displaying any local private data."""
import base64
import ctypes
from ctypes import wintypes
import fnmatch
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENIED_PARTS = {".git", "upstream_local", "node_modules", ".runtime", ".upstream-runtime", "output", "private", "exports", "offline-profile", "validation-output", ".source-cache", "__pycache__"}
DENIED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".key", ".pem", ".pfx", ".p12", ".exe", ".dll", ".pyd", ".zip", ".pcap", ".pcapng", ".log", ".pyc"}

class Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

def decrypt_local(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format") != "windows-dpapi-user/1": return value
    raw = base64.b64decode(value["encrypted"])
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    if not crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise RuntimeError("Cannot audit local credential exclusion")
    try: return json.loads(ctypes.string_at(destination.data, destination.length))
    finally:
        kernel = ctypes.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(destination.data)

def private_markers():
    markers = set()
    directory = ROOT / "upstream_local/output"
    accounts = directory / "databases"
    if accounts.exists():
        markers.update(path.name.encode() for path in accounts.iterdir() if path.is_dir() and len(path.name) >= 6)
    def inspect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"db_key", "api_key", "image_aes_key", "auth_key", "auth_key_hex", "aeskey", "capability", "fileid", "expected_md5", "reference_sha256"} and isinstance(item, str) and len(item) >= 12:
                    markers.add(item.encode())
                elif key == "text" and isinstance(item, str) and len(item) >= 80:
                    markers.update(item[offset:offset + 80].encode() for offset in range(0, len(item) - 79, 80))
                else: inspect(item)
        elif isinstance(value, list):
            for item in value: inspect(item)
    for name in ("account_keys.json", "ai_settings.json", "chatgpt_context_grant.json"):
        path = directory / name
        if path.exists(): inspect(decrypt_local(path))
    if accounts.exists():
        for path in accounts.glob('*/_local_cdn_profile.dpapi.json'): inspect(decrypt_local(path))
    private = ROOT / 'private'
    if private.exists():
        for path in private.glob('cdn*.dpapi.json'): inspect(decrypt_local(path))
    return markers

def audit(*, transport=False):
    paths = json.loads((ROOT / "scripts/publication-files.json").read_text(encoding="utf-8"))["files"]
    markers = private_markers()
    inventory, elements = [], []
    for relative in paths:
        path = ROOT / relative
        if (not path.resolve().is_relative_to(ROOT.resolve()) or set(Path(relative).parts) & DENIED_PARTS
                or path.suffix.lower() in DENIED_SUFFIXES or path.name.startswith(".env")
                or any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in ("*global_config*", "*account_keys*", "*ai_settings*", "*context_grant*"))):
            raise ValueError("Forbidden publication path: " + relative)
        raw = path.read_bytes()
        content = raw.decode("utf-8").replace("\r\n", "\n")
        inspected = [content.encode()]
        if relative == "source-overlay/source-changes.json":
            inspected += [base64.b64decode(edit["insert_base64"]) for change in json.loads(content)["changes"] for edit in change["edits"]]
        if any(marker in data for marker in markers for data in inspected):
            raise ValueError("Local private marker found in publication candidate: " + relative)
        if any(phrase in content for phrase in ("-----BEGIN " + "PRIVATE KEY-----", "-----BEGIN " + "RSA PRIVATE KEY-----")):
            raise ValueError("Private key material found: " + relative)
        inventory.append({"path": relative, "sha256": hashlib.sha256(content.encode()).hexdigest(), "bytes": len(content.encode())})
        elements.append({"path": relative, "mode": "100644", "type": "blob", "content": content})
    report = {"passed": True, "files": len(paths), "bytes": sum(item["bytes"] for item in inventory),
              "private_markers_checked": len(markers), "inventory": inventory}
    validation = ROOT / "validation-output"
    validation.mkdir(exist_ok=True)
    (validation / "publication-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if transport:
        (validation / "publication-tree.json").write_text(json.dumps(elements, ensure_ascii=False), encoding="utf-8")
    return {key: value for key, value in report.items() if key != "inventory"}

if __name__ == "__main__": print(json.dumps(audit(transport=True)))
