"""Mandatory offline policy for this private local fork. No opt-out setting."""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from contextvars import ContextVar
import hmac
import importlib.abc
import logging
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit, unquote


class OfflinePolicyError(PermissionError):
    pass


def blocked_feature(*_args, **_kwargs):
    raise OfflinePolicyError("此功能需要外部服务或尚未审查的原生组件，离线版本已禁用。")


_installed = False
_backend_port = int(os.environ.get("WECHAT_TOOL_PORT", "10392"))
_allowed_ips = {"127.0.0.1", "::1"}
_local_model_target = ContextVar("explicit_local_model_connection", default=None)


@contextmanager
def local_model_connection(host, port):
    if host not in _allowed_ips or not isinstance(port, int) or port < 1024 or port > 65535 or port == _backend_port:
        raise OfflinePolicyError("仅允许单独配置的本机模型端口。")
    token = _local_model_target.set((host, port))
    try:
        yield
    finally:
        _local_model_target.reset(token)


def _network_address_allowed(address):
    return isinstance(address, tuple) and len(address) >= 2 and address[0] in _allowed_ips and address[1] == _backend_port


def _stdlib_socketpair():
    # asyncio on Windows creates an internal loopback socketpair at an ephemeral port.
    frame = sys._getframe(1)
    for _ in range(12):
        if frame is None:
            break
        filename = frame.f_code.co_filename.replace("\\", "/").lower()
        if frame.f_code.co_name in {"socketpair", "_fallback_socketpair"} and filename.endswith("/lib/socket.py"):
            return True
        frame = frame.f_back
    return False


def install():
    global _installed
    if _installed:
        return
    _installed = True
    # Avoid inherited proxy, model-download, and telemetry settings.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(name, None)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      DO_NOT_TRACK="1", WECHAT_TOOL_HOST="127.0.0.1", WECHAT_TOOL_ALLOW_REMOTE_CALLS="0")
    logging.disable(logging.CRITICAL)
    kernel = None
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel.GetDriveTypeW.restype = ctypes.c_uint
        kernel.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        kernel.GetFileAttributesW.restype = ctypes.c_uint

    def check_path(value):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return
        path = os.fsdecode(value)
        if path.startswith("file:"):
            uri = urlsplit(path)
            if uri.netloc:
                raise OfflinePolicyError("离线版本禁止网络数据库 URI。")
            path = unquote(uri.path)
            if path == ":memory:":
                return
            if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
                path = path[1:]
        if path.startswith(("\\\\", "//")):
            raise OfflinePolicyError("离线版本禁止网络/设备路径。")
        if kernel is not None:
            full = os.path.abspath(path)
            drive, tail = os.path.splitdrive(full)
            if drive and kernel.GetDriveTypeW(drive + "\\") != 3:
                raise OfflinePolicyError("离线版本只允许本机固定磁盘。")
            if ":" in tail:
                raise OfflinePolicyError("离线版本禁止备用数据流。")
            current = drive + "\\"
            for part in tail.replace("/", "\\").split("\\"):
                if not part:
                    continue
                current = os.path.join(current, part)
                attrs = kernel.GetFileAttributesW(current)
                if attrs != 0xFFFFFFFF and attrs & 0x400:
                    raise OfflinePolicyError("离线版本禁止目录联接、符号链接和云占位文件。")

    def audit(event, args):
        if event in {"socket.connect", "socket.bind", "socket.sendto"}:
            model_request = (event == "socket.connect" and _local_model_target.get() is not None
                             and isinstance(args[-1], tuple) and args[-1][:2] == _local_model_target.get())
            if not _network_address_allowed(args[-1]) and not model_request and not (
                event != "socket.sendto" and _stdlib_socketpair() and isinstance(args[-1], tuple) and args[-1][0] in _allowed_ips
            ):
                raise OfflinePolicyError("已阻止非本应用回环地址的网络操作。")
        elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            if args[0] not in _allowed_ips:
                raise OfflinePolicyError("离线版本禁止 DNS 查询。")
        elif event.startswith(("subprocess.", "os.spawn", "os.exec", "os.startfile")) or event in {"os.system", "os.posix_spawn"}:
            raise OfflinePolicyError("离线后端禁止启动外部进程。")
        elif event in {"open", "os.listdir", "os.scandir", "sqlite3.connect"}:
            if args and args[0] != ":memory:":
                check_path(args[0])
        elif event == "ctypes.dlopen":
            path = str(args[0] or "").lower().replace("\\", "/")
            if "/native/" in path or "wx_key" in path or "wechatdb" in path or "voipengine" in path or "img_helper" in path:
                blocked_feature()
        elif event == "sqlite3.load_extension":
            blocked_feature()
    sys.addaudithook(audit)

    # stat/resolve can initiate SMB authentication before open() runs. Validate first.
    def wrap_path_function(function, path_count=1):
        def local_only(*args, **kwargs):
            for value in args[:path_count]:
                check_path(value)
            return function(*args, **kwargs)
        return local_only
    for name in ("stat", "lstat", "access", "readlink"):
        if hasattr(os, name):
            setattr(os, name, wrap_path_function(getattr(os, name)))
    os.path.realpath = wrap_path_function(os.path.realpath)

    class RejectOpaqueModules(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "wx_key" or fullname.startswith("wx_key.") or fullname.startswith("wechat_decrypt_tool.native."):
                raise ImportError("Unreviewed upstream native module disabled in offline fork")
            return None
    sys.meta_path.insert(0, RejectOpaqueModules())


CSP = "; ".join((
    "default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:", "font-src 'self' data:", "media-src 'self' blob: data:",
    "connect-src 'self'", "worker-src 'self' blob:", "frame-src 'none'", "object-src 'none'",
    "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'",
))


class OfflineAccessMiddleware:
    """Same-origin, secret-header access from the dedicated Electron session only."""
    def __init__(self, app):
        self.app = app
        self.token = os.environ.get("WECHAT_TOOL_OFFLINE_TOKEN", "")
        if len(self.token) < 32:
            raise OfflinePolicyError("必须由本地离线桌面启动器启动后端。")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("ascii", "ignore")
        expected_host = f"127.0.0.1:{_backend_port}"
        origin = headers.get(b"origin", b"").decode("ascii", "ignore")
        token = headers.get(b"x-offline-token", b"").decode("ascii", "ignore")
        client = scope.get("client")
        allowed = (host == expected_host and (not origin or origin == "http://" + expected_host)
                   and client and client[0] in _allowed_ips and hmac.compare_digest(token, self.token))
        if not allowed:
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"text/plain"), (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": b"Local authenticated access required"})
            return

        path = scope.get("path", "")
        unavailable = (
            path.startswith(("/api/cdn/", "/api/macos-key-capture/"))
            or path in {"/api/system/img_helper/toggle", "/api/chat/media/favicon", "/api/chat/media/emoji/download",
                        "/api/sns/video_remote", "/api/sns/article_thumb", "/api/admin/port"}
            or (scope.get("method") == "POST" and ("/models/" in path and path.endswith("/download") or "/qwen-gpu/" in path))
            or "/voice/transcription/native" in path
        )
        if unavailable:
            body = b'{"detail":{"code":"OFFLINE_FEATURE_DISABLED","message":"This operation is disabled in the local offline build."}}'
            await send({"type": "http.response.start", "status": 409,
                        "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                                    (b"content-security-policy", CSP.encode()), (b"referrer-policy", b"no-referrer")]})
            await send({"type": "http.response.body", "body": body})
            return

        async def safe_send(message):
            if message["type"] == "http.response.start":
                response_headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in
                                    {b"content-security-policy", b"access-control-allow-origin", b"access-control-allow-credentials"}]
                response_headers += [(b"content-security-policy", CSP.encode()), (b"referrer-policy", b"no-referrer"),
                                     (b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-store")]
                message = dict(message, headers=response_headers)
            await send(message)
        await self.app(scope, receive, safe_send)
