"""Export names and complete-file replacement; conversion bytes stay untouched."""

import os
import tempfile
from pathlib import Path, PureWindowsPath


def export_filename(source, format, scale=1, custom=None):
    if custom is None:
        stem = "".join(c for c in source if c.isalnum() or c in "-_ ").strip()[:80] or "structure"
        suffix = f"_{scale:g}x" if scale > 1 else ""
        return f"{stem}_converted{suffix}.{format}"
    name = custom.strip()
    if (not name or len(name) > 200 or name.endswith(".")
            or any(ord(c) < 32 or ord(c) == 127 or c in '<>:"/\\|?*' for c in name)
            or PureWindowsPath(name).is_reserved()):
        raise ValueError("Enter a valid filename without a folder or path")
    for extension in (".nbt", ".litematic", ".blueprint"):
        if name.lower().endswith(extension):
            name = name[:-len(extension)]
            break
    if not name or PureWindowsPath(name).is_reserved():
        raise ValueError("Enter a valid filename")
    return f"{name}.{format}"


def atomic_save(destination, content):
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".fromthecraft-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
