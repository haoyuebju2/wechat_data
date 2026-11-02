"""Read-only Windows key acquisition using upstream source patterns, no wx_key DLL."""
from __future__ import annotations

import re
import time

from .image_key_memory_scan import _create_win32_api, _enumerate_scannable_regions, find_wechat_pids
from .wechat_decrypt import _resolve_page1_key_material

# Upstream key_v4's pointer / size / capacity signature, implemented without YARA.
POINTER_PATTERN = re.compile(rb"(.{8})\x00{8}\x20\x00{7}\x2f\x00{7}", re.DOTALL)


def iter_candidate_pointers(data):
    for match in POINTER_PATTERN.finditer(data):
        pointer = int.from_bytes(match.group(1), "little")
        if 0x10000 <= pointer <= 0x7FFF_FFFF_FFFF:
            yield pointer


def verify_candidate(candidate, first_page, masks, *, deadline=None, cancel_event=None):
    if len(candidate) != 32:
        return None
    for mask in masks:
        if (deadline is not None and time.monotonic() >= deadline) or (cancel_event is not None and cancel_event.is_set()):
            raise TimeoutError("本地只读密钥验证已结束。")
        key = bytes(a ^ b for a, b in zip(candidate, mask)) if mask else candidate
        if _resolve_page1_key_material(key, first_page) is not None:
            return key
    return None


def candidate_priority(candidate):
    # Ordinary strings also have a 32-byte std::string representation. Test
    # binary candidates first, as upstream key_v4's entropy filter does, but
    # retain printable candidates as a fallback instead of rejecting them.
    return sum(32 <= byte <= 126 for byte in candidate) > 24


def get_local_database_key(db_storage_path, *, internal_db_key=None, wechat_install_path=None,
                           cancel_event=None, timeout_seconds=120.0):
    from .key_service import _resolve_v4_probe_db_file, _normalize_internal_db_key, _resolve_wechat_dll_path
    from .dll_key_scan import extract_xor_keys_from_dll
    probe = _resolve_v4_probe_db_file(db_storage_path)
    with probe.open("rb") as stream:
        first_page = stream.read(4096)
    if len(first_page) != 4096 or first_page.startswith(b"SQLite format 3\0"):
        raise RuntimeError("请选择本账号的完整加密数据库作为密钥验证依据。")
    masks = [b""]
    manual = _normalize_internal_db_key(internal_db_key)
    if manual:
        masks.append(manual)
    else:
        try:
            dll = _resolve_wechat_dll_path(wechat_install_path)
            # Parse the DLL as a file; never load it into this process.
            for item in extract_xor_keys_from_dll(dll, max_workers=1):
                mask = bytes.fromhex(item["key_hex"])
                if len(mask) == 32 and mask not in masks:
                    masks.append(mask)
                if len(masks) >= 17:
                    break
        except (OSError, RuntimeError, ValueError):
            pass
    api = _create_win32_api()
    if api is None:
        raise RuntimeError("当前平台无法提供 Windows 只读进程接口。")
    pids = find_wechat_pids()
    if not pids:
        raise RuntimeError("未找到运行中的微信主进程，请先在本机登录微信。")
    deadline = time.monotonic() + max(1, min(float(timeout_seconds), 300))
    seen = set()
    candidates = []
    for pid in pids:
        handle = api.open_process(pid)
        if not handle:
            continue
        try:
            for region in _enumerate_scannable_regions(api, handle, deadline=deadline):
                for offset in range(0, region.size, 4 * 1024 * 1024):
                    if time.monotonic() >= deadline or (cancel_event is not None and cancel_event.is_set()):
                        raise TimeoutError("本地只读扫描已结束，未取得通过认证的密钥。")
                    data = api.read_memory(handle, region.base_address + offset, min(4 * 1024 * 1024 + 31, region.size - offset))
                    for pointer in iter_candidate_pointers(data):
                        candidate = api.read_memory(handle, pointer, 32)
                        if len(candidate) != 32 or candidate in seen or len(set(candidate)) < 15:
                            continue
                        seen.add(candidate)
                        if len(seen) > 4096:
                            raise RuntimeError("候选数量超出安全上限，请检查微信版本是否需要适配。")
                        candidates.append(candidate)
        finally:
            api.close_handle(handle)
    # Finish the cheap discovery phase across all WeChat processes before
    # spending the deadline on PBKDF2. Text in a helper process must not starve
    # the main process's real key. Keep the process boundary read-only.
    candidates.sort(key=candidate_priority)
    for candidate in candidates:
        key = verify_candidate(candidate, first_page, masks, deadline=deadline, cancel_event=cancel_event)
        if key is not None:
            return {"db_key": key.hex(), "method": "local_source_memory_scan",
                    "db_key_probe_path": str(probe), "verified": True}
    raise RuntimeError("未找到通过本账号数据库认证的密钥；未调用 DLL Hook 或任何远程兜底。")
