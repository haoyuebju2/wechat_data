"""Process policy and local-file boundary; Windows Firewall is the OS boundary."""
import ctypes
import os
from pathlib import Path
import sys


class SafeError(Exception):
    """Only fixed, non-sensitive messages should be displayed to the user."""


_job_handle = None


def restrict_child_processes():
    """An active-process-limit Windows Job also blocks native/Tcl child creation."""
    global _job_handle
    if os.name != "nt":
        raise SafeError("标准安全启动目前只支持 Windows。")
    from ctypes import wintypes as w
    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]
    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    k.CreateJobObjectW.restype = w.HANDLE
    k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k.SetInformationJobObject.restype = w.BOOL
    k.GetCurrentProcess.restype = w.HANDLE
    k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    k.AssignProcessToJobObject.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    handle = k.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 8  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    limits.BasicLimitInformation.ActiveProcessLimit = 1
    if not handle or not k.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not k.AssignProcessToJobObject(handle, k.GetCurrentProcess()):
        if handle:
            k.CloseHandle(handle)
        raise SafeError("无法启用 Windows 子进程限制，已停止启动。")
    _job_handle = handle  # Keep it alive for this process's entire lifetime.


def local_path(value, *, exists=True):
    raw = os.fspath(value)
    if raw.startswith(("\\\\", "//")) or "://" in raw:
        raise SafeError("禁止网络路径、UNC 路径及设备路径。请选择本机磁盘。")
    p = Path(raw).expanduser().absolute()
    if os.name == "nt":
        # Reject alternate data streams and remote mapped drives BEFORE file access.
        if ":" in str(p)[2:]:
            raise SafeError("不支持设备路径或备用数据流。")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel.GetDriveTypeW.restype = ctypes.c_uint
        if kernel.GetDriveTypeW(p.anchor) != 3:
            raise SafeError("只允许本机固定磁盘，不允许映射网络盘或可移动盘。")
        # Reject reparse points without traversing their targets.
        kernel.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        kernel.GetFileAttributesW.restype = ctypes.c_uint
        for part in [*reversed(p.parents), p]:
            attrs = kernel.GetFileAttributesW(str(part))
            if attrs != 0xFFFFFFFF and attrs & 0x400:
                raise SafeError("不允许符号链接、目录联接或云端占位文件。")
    elif any(x.is_symlink() for x in [p, *p.parents]):
        raise SafeError("不允许符号链接。")
    if exists and not p.exists():
        raise SafeError("所选文件或目录不存在。")
    return p


def install_guard():
    """Defense in depth, not a replacement for a network-disabled OS sandbox."""
    blocked = ("socket.", "subprocess.", "os.spawn", "os.exec", "os.startfile")

    def audit(event, args):
        if event.startswith(blocked) or event in {"os.system", "os.posix_spawn"}:
            raise SafeError("离线策略已阻止网络或子进程操作。")
        if event == "sqlite3.load_extension":
            raise SafeError("离线策略禁止加载 SQLite 扩展。")
        if event == "ctypes.dlopen":
            name = str(args[0]).lower()
            if name not in {"kernel32", "bcrypt.dll"}:
                raise SafeError("离线策略禁止加载外部原生组件。")
    sys.addaudithook(audit)
