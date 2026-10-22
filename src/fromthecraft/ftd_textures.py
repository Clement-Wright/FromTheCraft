"""Read selected installed FtD Unity Resources textures without loading asset archives.

Only the local Resources name index, serialized metadata, selected Texture2D
objects and their bounded streamed pixel ranges are read. Nothing is extracted
to disk. UnityPy is optional so source users can keep the color-only fallback.
"""

import io
import importlib.util
from functools import lru_cache
import re
import struct
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

MAX_METADATA_BYTES = 128 * 1024**2
MAX_PIXEL_BYTES = 32 * 1024**2
MAX_PNG_BYTES = 16 * 1024**2
MAX_DIMENSION = 2048
MAX_TEXTURES = 256
MAX_ASSET_FILES = 16


class _BoundedStream:
    """A seekable file facade that rejects unbounded reads and caps total reads."""

    def __init__(self, stream, budget):
        self.stream = stream
        self.budget = budget if isinstance(budget, list) else [budget]

    def read(self, size=-1):
        if size is None or size < 0:
            raise ValueError("Unity asset reads must be bounded")
        if size > MAX_PIXEL_BYTES or size > self.budget[0]:
            raise ValueError("Unity asset read budget exceeded")
        self.budget[0] -= size
        return self.stream.read(size)

    def seek(self, offset, whence=0):
        return self.stream.seek(offset, whence)

    def tell(self):
        return self.stream.tell()


def _unity_types():
    from UnityPy.files import SerializedFile
    from UnityPy.streams import EndianBinaryReader

    return SerializedFile, EndianBinaryReader


def _resource_key(value):
    if not isinstance(value, str) or len(value) > 512 or "\\" in value or ":" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        return None
    if path.suffix.lower() == ".png":
        path = path.with_suffix("")
    return str(path).lower() if path.parts else None


def _local_file(root, name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_. -]+", name) or name in {".", ".."}:
        raise ValueError("Unity resource path must name one local file")
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Unity resource path escapes game data directory")
    return path


def _check_header(stream, file_size):
    head = stream.read(48)
    if len(head) < 20:
        raise ValueError("Truncated Unity metadata header")
    metadata, declared_size, version, offset = struct.unpack_from(">4I", head)
    if not 9 <= version <= 22:
        raise ValueError("Unsupported Unity serialized file version")
    if version >= 22:
        if len(head) < 48:
            raise ValueError("Truncated Unity metadata header")
        metadata, declared_size, offset = struct.unpack_from(">Iqq", head, 20)
    if metadata > MAX_METADATA_BYTES or not 20 <= offset <= file_size or declared_size != file_size:
        raise ValueError("Invalid or oversized Unity metadata")
    if metadata > offset:
        raise ValueError("Invalid Unity metadata bounds")
    stream.seek(0)


@lru_cache(maxsize=1)
def _texture_decoder():
    import UnityPy

    # UnityPy.export eagerly imports its audio converter and FMOD. Load the pinned
    # texture-only module directly so this image reader needs no audio runtime.
    path = Path(UnityPy.__file__).parent / "export" / "Texture2DConverter.py"
    spec = importlib.util.spec_from_file_location("UnityPy.export._fromthecraft_texture", path)
    if spec is None or spec.loader is None:
        raise ImportError("UnityPy texture decoder is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_image_from_texture2d


def _decode_texture(texture):
    return _texture_decoder()(texture)


def _pixel_png(texture, root):
    width, height = texture.m_Width, texture.m_Height
    if not 0 < width <= MAX_DIMENSION or not 0 < height <= MAX_DIMENSION:
        return None
    payload = texture.image_data
    if len(payload) > MAX_PIXEL_BYTES:
        return None
    info = texture.m_StreamData
    if not payload and info is not None and info.size:
        size, offset = info.size, info.offset
        if (
            not isinstance(size, int)
            or not isinstance(offset, int)
            or not 0 < size <= MAX_PIXEL_BYTES
            or offset < 0
        ):
            return None
        path = _local_file(root, info.path)
        if offset + size > path.stat().st_size:
            return None
        with path.open("rb") as stream:
            bounded = _BoundedStream(stream, size)
            bounded.seek(offset)
            payload = bounded.read(size)
        if len(payload) != size:
            return None
        # Supplying only this selected range prevents UnityPy dependency loading.
        texture.image_data = payload
    if not payload:
        return None
    image = _decode_texture(texture)
    try:
        if image.size != (width, height):
            return None
        output = io.BytesIO()
        image.save(output, format="PNG")
        content = output.getvalue()
        return content if len(content) <= MAX_PNG_BYTES else None
    finally:
        image.close()


def extract_base_colors(game_data_path: Path, wanted: set[str]) -> dict[str, bytes]:
    """Return PNGs keyed by requested Resources paths; missing/unsupported images are omitted."""
    if len(wanted) > MAX_TEXTURES:
        raise ValueError("Too many requested FtD color textures")
    requested = {}
    for name in wanted:
        key = _resource_key(name)
        if key:
            requested.setdefault(key, []).append(name)
    if not requested:
        return {}
    try:
        serialized_file, endian_reader = _unity_types()
    except ImportError:
        return {}
    root = Path(game_data_path).resolve()
    if root.name == "StreamingAssets":
        root = root.parent
    elif (root / "From_The_Depths_Data").is_dir():
        root = root / "From_The_Depths_Data"
    root = root.resolve()
    images, files, budget = {}, {}, [MAX_METADATA_BYTES]
    try:
        with ExitStack() as stack:

            def asset(name):
                if name in files:
                    return files[name]
                if len(files) >= MAX_ASSET_FILES:
                    raise ValueError("Too many Unity asset dependencies")
                path = _local_file(root, name)
                stream = stack.enter_context(path.open("rb"))
                bounded = _BoundedStream(stream, budget)
                _check_header(bounded, path.stat().st_size)
                loaded = serialized_file(endian_reader(bounded), name=name)
                files[name] = loaded
                return loaded

            manager_file = asset("globalgamemanagers")
            for obj in manager_file.objects.values():
                if obj.type.name != "ResourceManager" or obj.byte_size > MAX_METADATA_BYTES:
                    continue
                for resource_name, pointer in obj.read().m_Container:
                    key = _resource_key(resource_name)
                    if key not in requested:
                        continue
                    try:
                        file_id = pointer.m_FileID
                        if file_id == 0:
                            owner = manager_file
                        elif 1 <= file_id <= len(manager_file.externals):
                            owner = asset(manager_file.externals[file_id - 1].path)
                        else:
                            continue
                        target = owner.objects.get(pointer.m_PathID)
                        if (
                            target is None
                            or target.type.name != "Texture2D"
                            or target.byte_size > MAX_PIXEL_BYTES
                        ):
                            continue
                        content = _pixel_png(target.read(), root)
                        if content is not None:
                            if sum(map(len, images.values())) + len(content) > MAX_METADATA_BYTES:
                                return images
                            for original in requested[key]:
                                images[original] = content
                    except (
                        OSError,
                        ValueError,
                        TypeError,
                        AttributeError,
                        EOFError,
                        struct.error,
                        NotImplementedError,
                    ):
                        continue
    except (OSError, ValueError, TypeError, AttributeError, EOFError, struct.error, NotImplementedError):
        return images
    return images
