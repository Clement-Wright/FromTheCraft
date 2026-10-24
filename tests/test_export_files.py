from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_failed_atomic_save_preserves_existing_file_and_cleans_temporary(monkeypatch, tmp_path):
    from fromthecraft import exporting

    destination = tmp_path / "existing.nbt"
    destination.write_bytes(b"original")

    def denied(*_):
        raise PermissionError("Read-only folder")

    monkeypatch.setattr(exporting.os, "replace", denied)
    with pytest.raises(PermissionError):
        exporting.atomic_save(destination, b"converted")
    assert destination.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [destination]


def test_export_extension_and_unicode_default():
    from fromthecraft.exporting import export_filename

    assert export_filename("船 design", "blueprint", 3) == "船 design_converted_3x.blueprint"
    assert export_filename("ship", "litematic", .5) == "ship_converted.litematic"
    assert export_filename("ship", "blueprint", 1, "design.v2") == "design.v2.blueprint"
    assert Path(export_filename("ship", "nbt", 2, "custom.NBT")).suffix.lower() == ".nbt"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows dialog binding")
def test_native_save_does_not_attach_to_an_unrelated_foreground_window(monkeypatch):
    from fromthecraft import native_save

    owners, windows = [], []

    def cancelled(options):
        owners.append(options._obj.hwndOwner or 0)
        hook_type = native_save.ctypes.WINFUNCTYPE(native_save.ctypes.c_size_t, native_save.wintypes.HWND,
            native_save.wintypes.UINT, native_save.wintypes.WPARAM, native_save.wintypes.LPARAM)
        if options._obj.lpfnHook:
            hook_type(options._obj.lpfnHook)(10, 0x110, 0, 0)
        return False

    dialog = SimpleNamespace(GetSaveFileNameW=Mock(side_effect=cancelled), CommDlgExtendedError=Mock(return_value=0))
    unrelated_app = SimpleNamespace(GetForegroundWindow=Mock(return_value=0xABCD), GetParent=Mock(return_value=20),
        SetWindowPos=Mock(side_effect=lambda *args: windows.append(args)), SetForegroundWindow=Mock(return_value=1))
    monkeypatch.setattr(native_save.ctypes, "WinDLL", lambda name, **_: dialog if name == "comdlg32" else unrelated_app)
    assert native_save.choose_save_file("ship.nbt") is None
    assert native_save.choose_save_file("ship.nbt") is None
    assert owners == [0, 0], "A local web request must not make an unrelated foreground app the modal owner"
    assert len(windows) == 2 and all(row[0] == 20 and row[-1] & 0x40 for row in windows), \
        "The requested save dialog must become visible even when its process was launched hidden"
