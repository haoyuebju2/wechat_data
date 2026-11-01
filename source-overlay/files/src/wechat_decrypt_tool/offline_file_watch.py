"""Windows directory notifications, using only the system Kernel32 API."""
import ctypes
from ctypes import wintypes
from pathlib import Path


class LocalChangeNotification:
    def __init__(self, directory: Path):
        # resolve/stat run the mandatory offline guard before the native API.
        directory = directory.resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("local_directory_required")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        kernel.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        kernel.FindNextChangeNotification.argtypes = [wintypes.HANDLE]
        kernel.FindNextChangeNotification.restype = wintypes.BOOL
        kernel.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
        kernel.FindCloseChangeNotification.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel = kernel
        self.handle = kernel.FindFirstChangeNotificationW(str(directory), True, 0x01 | 0x02 | 0x08 | 0x10)
        if self.handle == ctypes.c_void_p(-1).value:
            self.handle = None
            raise OSError("local_watch_unavailable")

    def wait(self, milliseconds=100):
        code = self.kernel.WaitForSingleObject(self.handle, milliseconds)
        if code == 0:
            if not self.kernel.FindNextChangeNotification(self.handle):
                raise OSError("local_watch_rearm_failed")
            return True
        if code != 258:  # WAIT_TIMEOUT
            raise OSError("local_watch_wait_failed")
        return False

    def close(self):
        if self.handle is not None:
            self.kernel.FindCloseChangeNotification(self.handle)
            self.handle = None
