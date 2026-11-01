"""Explicit local-model requests and one-use, encrypted desktop context grants."""
from contextlib import contextmanager
import json
import msvcrt
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
import httpx

from .app_paths import get_output_dir
from .offline_policy import local_model_connection
from .offline_secrets import FORMAT, read_secret_json, write_secret_json

_config_lock = threading.RLock()
MAX_TEXT = 32768


def _encrypted(path):
    if not path.exists():
        return {}
    if json.loads(path.read_text(encoding="utf-8")).get("format") != FORMAT:
        raise ValueError("encrypted_settings_required")
    value = read_secret_json(path)
    if not isinstance(value, dict):
        raise ValueError("invalid_settings")
    return value


def validate_endpoint(url):
    parsed = urlsplit(str(url).strip())
    host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
    port = parsed.port
    if (parsed.scheme != "http" or host not in {"127.0.0.1", "::1"} or not port
            or not 1024 <= port <= 65535 or port == 10392 or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip("/") not in {"", "/v1"}):
        raise ValueError("only_numeric_loopback_model_endpoint")
    netloc = f"[{host}]:{port}" if host == "::1" else f"{host}:{port}"
    return f"http://{netloc}/v1", host, port


def load_settings():
    with _config_lock:
        value = _encrypted(get_output_dir() / "ai_settings.json")
    if not value:
        return {"enabled": False, "base_url": "http://127.0.0.1:11434/v1", "model": "", "api_key": ""}
    validate_endpoint(value.get("base_url", ""))
    return value


def public_settings():
    value = load_settings()
    return {key: value.get(key) for key in ("enabled", "base_url", "model")} | {"key_present": bool(value.get("api_key"))}


def save_settings(enabled, base_url, model, api_key=None):
    endpoint, _, _ = validate_endpoint(base_url)
    if not isinstance(model, str) or len(model) > 200 or (enabled and not model.strip()):
        raise ValueError("model_required")
    with _config_lock:
        previous = load_settings()
        # Never carry credentials to a changed endpoint without explicit re-entry.
        key = previous.get("api_key", "") if api_key is None and previous["base_url"] == endpoint else (api_key or "")
        if len(key) > 2048 or "\n" in key or "\r" in key:
            raise ValueError("invalid_api_key")
        write_secret_json(get_output_dir() / "ai_settings.json", {"enabled": bool(enabled), "base_url": endpoint,
                                                                 "model": model.strip(), "api_key": key})
    return public_settings()


def local_completion(messages):
    value = load_settings()
    if value.get("enabled") is not True:
        raise ValueError("local_model_disabled")
    endpoint, host, port = validate_endpoint(value["base_url"])
    if not messages or len(messages) > 40 or sum(len(item.get("content", "")) for item in messages) > 100000:
        raise ValueError("invalid_prompt_size")
    if any(item.get("role") not in {"user", "assistant"} or not isinstance(item.get("content"), str) for item in messages):
        raise ValueError("invalid_prompt")
    headers = {"Authorization": "Bearer " + value["api_key"]} if value.get("api_key") else {}
    # No redirects, proxies, DNS hostnames, tools, file access or automatic context gathering.
    with local_model_connection(host, port):
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(120, connect=3)) as client:
            with client.stream("POST", endpoint + "/chat/completions", headers=headers,
                               json={"model": value["model"], "messages": messages, "stream": False, "max_tokens": 2048}) as response:
                if response.status_code != 200:
                    raise ValueError("model_request_failed")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("model_reply_too_large")
    result = json.loads(body)
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("unsupported_model_reply")
    return content


@contextmanager
def _grant_lock():
    root = get_output_dir()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".ai-grant.lock").open("a+b") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + 3
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError("grant_busy") from None
                time.sleep(.01)
        try:
            yield root / "chatgpt_context_grant.json"
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def grant_status():
    with _grant_lock() as path:
        value = _encrypted(path)
    active = value.get("active") is True and value.get("expires_at", 0) > time.time()
    return {"active": active, "expires_at": value.get("expires_at") if active else None,
            "characters": len(value.get("text", "")) if active else 0}


def create_grant(text, cloud_ack):
    if cloud_ack is not True or not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError("explicit_cloud_ack_and_preview_required")
    with _grant_lock() as path:
        write_secret_json(path, {"active": True, "expires_at": time.time() + 600, "text": text})
    return grant_status()


def revoke_grant():
    with _grant_lock() as path:
        write_secret_json(path, {"active": False})
    return {"active": False}


def consume_grant():
    with _grant_lock() as path:
        value = _encrypted(path)
        if value.get("active") is not True or value.get("expires_at", 0) <= time.time():
            raise ValueError("no_active_grant")
        text = value.get("text")
        if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT:
            raise ValueError("invalid_grant")
        # Consume before releasing any content. Only one concurrent client wins.
        write_secret_json(path, {"active": False, "consumed_at": time.time()})
        return text
