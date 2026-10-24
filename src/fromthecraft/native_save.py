"""Windows Save As without another GUI runtime dependency."""

import ctypes
import sys
import threading
from ctypes import wintypes
from pathlib import Path

_dialog_lock = threading.Lock()


class OpenFilename(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE), ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD), ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD), ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD), ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD), ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


def choose_save_file(filename, directory=""):
    if sys.platform != "win32":
        raise OSError("Native Save As is available on Windows")
    if not _dialog_lock.acquire(blocking=False):
        raise OSError("A save dialog is already open")
    try:
        dialog = ctypes.WinDLL("comdlg32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetForegroundWindow.argtypes = []
        user.GetForegroundWindow.restype = wintypes.HWND
        dialog.GetSaveFileNameW.argtypes = [ctypes.POINTER(OpenFilename)]
        dialog.GetSaveFileNameW.restype = wintypes.BOOL
        dialog.CommDlgExtendedError.argtypes = []
        dialog.CommDlgExtendedError.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(filename, 32768)
        extension = Path(filename).suffix.lstrip(".")
        options = OpenFilename(
            lStructSize=ctypes.sizeof(OpenFilename), hwndOwner=user.GetForegroundWindow(),
            lpstrFilter=f"Converted structure (*.{extension})\0*.{extension}\0\0",
            nFilterIndex=1, lpstrFile=ctypes.cast(buffer, wintypes.LPWSTR), nMaxFile=len(buffer),
            lpstrInitialDir=directory or None, lpstrTitle="Save converted structure",
            # Explorer UI, overwrite confirmation, existing folder, unchanged process CWD.
            Flags=0x80000 | 0x2 | 0x800 | 0x8, lpstrDefExt=extension,
        )
        if dialog.GetSaveFileNameW(ctypes.byref(options)):
            return Path(buffer.value)
        error = dialog.CommDlgExtendedError()
        if error:
            raise OSError(f"Windows could not open the save dialog (0x{error:x})")
        return None
    finally:
        _dialog_lock.release()
