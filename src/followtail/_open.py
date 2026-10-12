"""Open a file for reading without blocking its writer from rotating it."""

from __future__ import annotations

import io
import os
import sys

Identity = tuple[int, int]

# Windows reports a file that was deleted while another handle still holds it as
# "delete pending" (access denied) until that handle closes; treat it as gone.
_GONE_WINERRORS = frozenset({2, 3, 5, 32, 303})


def identity_of(status: os.stat_result) -> Identity:
    """The (device, inode) pair that tells two files with the same name apart."""
    return (status.st_dev, status.st_ino)


def is_gone(error: OSError) -> bool:
    """True when ``error`` means the name no longer leads to a readable file."""
    if isinstance(error, FileNotFoundError):
        return True
    winerror = getattr(error, "winerror", None)
    return isinstance(error, PermissionError) or winerror in _GONE_WINERRORS


if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _create_file = _kernel32.CreateFileW
    _create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _create_file.restype = wintypes.HANDLE
    _GENERIC_READ = 0x80000000
    # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE: the writer may keep
    # appending, truncate, rename or delete the file while we hold it open.
    _SHARE_ALL = 0x1 | 0x2 | 0x4
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _INVALID_HANDLE = wintypes.HANDLE(-1).value

    def _open_fd(path: str) -> int:
        handle = _create_file(
            path, _GENERIC_READ, _SHARE_ALL, None, _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None
        )
        if handle is None or handle == _INVALID_HANDLE:
            code = ctypes.get_last_error()
            raise OSError(0, ctypes.FormatError(code).strip(), path, code)
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except OSError:
            _kernel32.CloseHandle(wintypes.HANDLE(handle))
            raise

    def open_shared(path: str) -> io.FileIO:
        """Open ``path`` read only with every share mode, so rotation still works."""
        return io.FileIO(_open_fd(path), "rb", closefd=True)

else:

    def open_shared(path: str) -> io.FileIO:
        """Open ``path`` read only; POSIX never blocks a rename or unlink of open files."""
        return io.FileIO(path, "rb")
