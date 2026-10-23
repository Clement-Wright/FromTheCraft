"""Read local texture assets without executing, extracting, or redistributing archives."""

import io
import json
import os
import re
import secrets
import struct
import threading
import zipfile
import zlib
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_BYTES = 128 * 1024**2
MAX_EXPANDED_BYTES = 512 * 1024**2
MAX_MEMBERS = 160_000
MAX_IMAGE_BYTES = 16 * 1024**2
MAX_IMAGE_DIMENSION = 2048
MAX_JSON_BYTES = 2 * 1024**2
FACES = ("east", "west", "up", "down", "south", "north")
VECTORS = {
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "down": (0, -1, 0),
    "south": (0, 0, 1),
    "north": (0, 0, -1),
}
RESOURCE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")


def _resource(value, namespace="minecraft"):
    if not isinstance(value, str):
        return None
    value = value if ":" in value else f"{namespace}:{value}"
    if (
        len(value) > 512
        or not RESOURCE.fullmatch(value)
        or any(part == ".." for part in value.split(":", 1)[1].split("/"))
    ):
        return None
    return value


def _member(name):
    path = PurePosixPath(name)
    if "\\" in name or path.is_absolute() or ".." in path.parts or ":" in name or "\0" in name:
        raise ValueError("Unsafe archive member path")
    return str(path)


def _png(content):
    if len(content) > MAX_IMAGE_BYTES or content[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    offset, width, height, ended, image_data = 8, 0, 0, False, False
    inflater, decoded = zlib.decompressobj(), 0
    while offset + 12 <= len(content):
        size = int.from_bytes(content[offset : offset + 4], "big")
        kind = content[offset + 4 : offset + 8]
        end = offset + 8 + size
        if end + 4 > len(content) or zlib.crc32(content[offset + 4 : end]) != int.from_bytes(
            content[end : end + 4], "big"
        ):
            return False
        if offset == 8:
            if kind != b"IHDR" or size != 13:
                return False
            width, height = struct.unpack(">II", content[offset + 8 : offset + 16])
            if not (0 < width <= MAX_IMAGE_DIMENSION and 0 < height <= MAX_IMAGE_DIMENSION):
                return False
        if kind == b"IEND":
            ended = size == 0 and end + 4 == len(content)
            break
        if kind == b"IDAT" and size:
            image_data = True
            try:
                limit = width * height * 8 + height * 8 + 32
                decoded += len(inflater.decompress(content[offset + 8 : end], limit - decoded + 1))
                if decoded > limit or inflater.unconsumed_tail:
                    return False
            except zlib.error:
                return False
        offset = end + 4
    return ended and image_data and inflater.eof and bool(width and height)


class TextureLibrary:
    def __init__(self, minecraft_root=None, ftd_root=None, discover=True):
        self._lock = threading.RLock()
        self._archives = []
        self._assets = {}
        self._sources = []
        self._bytes = self._expanded = self._members = 0
        self._images = {}
        self._image_keys = {}
        self._faces = {}
        self._models = {}
        self._mc_available = None
        self._ftd = {}
        self._reasons = {"minecraft": [], "ftd": []}
        if discover:
            mc = (
                Path(minecraft_root)
                if minecraft_root is not None
                else Path(
                    os.environ.get(
                        "FROMTHECRAFT_MINECRAFT", str(Path(os.environ.get("APPDATA", "")) / ".minecraft")
                    )
                )
            )
            if ftd_root is None:
                from .catalog import game_assets

                ftd_root = game_assets()
            self._discover_minecraft(mc)
            self._discover_ftd(Path(ftd_root))

    def _add_archive(self, content, name, kind):
        if len(content) > MAX_ARCHIVE_BYTES or self._bytes + len(content) > MAX_ARCHIVE_BYTES:
            raise ValueError("Texture archive memory limit exceeded (128 MiB)")
        if len(self._archives) >= 64:
            raise ValueError("Too many texture archives")
        # Check the central-directory count before ZipFile allocates an object
        # for every member, including members unrelated to textures.
        trailer = content.rfind(b"PK\x05\x06", max(0, len(content) - 65557))
        if trailer < 0 or trailer + 22 > len(content):
            raise ValueError("Invalid texture ZIP/JAR archive")
        members = int.from_bytes(content[trailer + 10 : trailer + 12], "little")
        if members + self._members > MAX_MEMBERS:
            raise ValueError(f"Texture archive members limit exceeded ({MAX_MEMBERS})")
        try:
            zipped = zipfile.ZipFile(io.BytesIO(content))
            entries = zipped.infolist()
            if len(entries) + self._members > MAX_MEMBERS:
                raise ValueError(f"Texture archive members limit exceeded ({MAX_MEMBERS})")
            expanded = sum(entry.file_size for entry in entries)
            if expanded + self._expanded > MAX_EXPANDED_BYTES:
                raise ValueError("Texture archive expanded size limit exceeded (512 MiB)")
            assets = {}
            for entry in entries:
                path = _member(entry.filename)
                if entry.flag_bits & 1:
                    raise ValueError("Encrypted texture archives are unsupported")
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError("Unsupported texture archive compression")
                if path.startswith("assets/") and path.endswith((".json", ".png")) and not entry.is_dir():
                    assets[path] = (zipped, entry)
        except (OSError, zipfile.BadZipFile, NotImplementedError) as exc:
            raise ValueError("Invalid texture ZIP/JAR archive") from exc
        self._archives.append(zipped)
        self._assets.update(assets)
        self._bytes += len(content)
        self._members += len(entries)
        self._expanded += expanded
        self._sources.append(
            {"name": Path(name.replace("\\", "/")).name[:160], "kind": kind, "assets": len(assets)}
        )
        self._faces.clear()
        self._models.clear()
        self._mc_available = None

    def add_archive(self, content: bytes, name: str) -> dict:
        with self._lock:
            self._add_archive(content, name, "import")
            return self.status()

    def _read(self, path, limit):
        asset = self._assets.get(path)
        if asset is None or asset[1].file_size > limit:
            return None
        try:
            with asset[0].open(asset[1]) as stream:
                content = stream.read(limit + 1)
            return content if len(content) <= limit else None
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, zlib.error):
            return None

    def _json(self, path):
        content = self._read(path, MAX_JSON_BYTES)
        if content is None:
            return {}
        try:
            value = json.loads(content)
            return value if isinstance(value, dict) else {}
        except (ValueError, UnicodeError, RecursionError):
            return {}

    def _model(self, name, seen=()):
        if name in seen or len(seen) >= 24:
            return {}
        if name in self._models:
            return self._models[name]
        namespace, path = name.split(":", 1)
        model = self._json(f"assets/{namespace}/models/{path}.json")
        if not model:
            return {}
        parent = _resource(model.get("parent"))
        inherited = self._model(parent, seen + (name,)) if parent else {}
        textures = inherited.get("textures", {}).copy()
        own = model.get("textures", {})
        if isinstance(own, dict):
            if len(own) > 512:
                return {}
            for key, value in own.items():
                if (
                    not isinstance(key, str)
                    or len(key) > 512
                    or not isinstance(value, str)
                    or len(value) > 512
                ):
                    return {}
                textures[key] = value
        if len(textures) > 512:
            return {}
        result = {"textures": textures, "elements": model.get("elements", inherited.get("elements", []))}
        self._models[name] = result
        if len(self._models) > 512:
            self._models.pop(next(iter(self._models)))
        return result

    def _texture_key(self, name):
        namespace, path = name.split(":", 1)
        asset_path = f"assets/{namespace}/textures/{path}.png"
        asset = self._assets.get(asset_path)
        if asset is None:
            return None
        identity = (id(asset[0]), asset[1].header_offset)
        if identity in self._image_keys:
            return self._image_keys[identity]
        content = self._read(asset_path, MAX_IMAGE_BYTES)
        if content is None or not _png(content):
            return None
        key = secrets.token_hex(16)
        self._image_keys[identity] = key
        self._images[key] = asset
        return key

    @staticmethod
    def _matches(condition, properties, depth=0):
        if not isinstance(condition, dict) or depth > 16:
            return False
        for key, value in condition.items():
            if key in ("OR", "AND"):
                if not isinstance(value, list):
                    return False
                matches = [TextureLibrary._matches(item, properties, depth + 1) for item in value[:128]]
                if not (any(matches) if key == "OR" else all(matches)):
                    return False
            elif not isinstance(value, str) or str(properties.get(key, "")) not in value.split("|"):
                return False
        return True

    @staticmethod
    def _rotated(face, x, y):
        a, b, c = VECTORS[face]
        for _ in range((x // 90) % 4):
            b, c = c, -b
        for _ in range((y // 90) % 4):
            a, c = -c, a
        return next(name for name, vector in VECTORS.items() if vector == (a, b, c))

    def block_faces(self, name, properties=()) -> dict:
        resource = _resource(name)
        if resource is None:
            return {}
        try:
            properties = dict(properties)
            if len(properties) > 64:
                return {}
            cache_key = (resource, tuple(sorted((str(key), str(value)) for key, value in properties.items())))
        except (TypeError, ValueError):
            return {}
        with self._lock:
            if cache_key in self._faces:
                return self._faces[cache_key].copy()
            namespace, path = resource.split(":", 1)
            state = self._json(f"assets/{namespace}/blockstates/{path}.json")
            applied = []
            variants = state.get("variants", {})
            if isinstance(variants, dict):
                for variant, model in variants.items():
                    try:
                        condition = dict(pair.split("=", 1) for pair in variant.split(",")) if variant else {}
                    except ValueError:
                        continue
                    if self._matches(condition, properties):
                        applied.append(model)
                        break
            multipart = state.get("multipart", [])
            if isinstance(multipart, list):
                for part in multipart[:256]:
                    if isinstance(part, dict) and self._matches(part.get("when", {}), properties):
                        applied.append(part.get("apply"))
            if not state:
                applied.append({"model": f"{namespace}:block/{path}"})
            faces = {}
            for application in applied:
                if isinstance(application, list):
                    application = application[0] if application else {}
                if not isinstance(application, dict):
                    continue
                model_name = _resource(application.get("model"))
                if model_name is None:
                    continue
                model = self._model(model_name)
                textures = model.get("textures", {})
                elements = model.get("elements", [])
                if not isinstance(elements, list):
                    continue
                x, y = application.get("x", 0), application.get("y", 0)
                if not isinstance(x, int) or not isinstance(y, int) or x % 90 or y % 90:
                    continue
                for element in elements[:256]:
                    face_defs = element.get("faces", {}) if isinstance(element, dict) else {}
                    if not isinstance(face_defs, dict):
                        continue
                    for face, definition in face_defs.items():
                        if face not in FACES or not isinstance(definition, dict):
                            continue
                        texture = definition.get("texture")
                        visited = set()
                        while isinstance(texture, str) and texture.startswith("#") and texture not in visited:
                            visited.add(texture)
                            texture = textures.get(texture[1:])
                        texture = _resource(texture)
                        key = self._texture_key(texture) if texture else None
                        if key:
                            faces[self._rotated(face, x, y)] = key
            self._faces[cache_key] = faces
            if len(self._faces) > 8192:
                self._faces.pop(next(iter(self._faces)))
            return faces.copy()

    def image(self, key) -> bytes:
        with self._lock:
            source = self._images[key]
            if isinstance(source, bytes):
                return source
            zipped, entry = source
            with zipped.open(entry) as stream:
                content = stream.read(MAX_IMAGE_BYTES + 1)
            if not _png(content):
                raise KeyError(key)
            return content

    def ftd_face(self, material):
        with self._lock:
            return self._ftd.get(str(material).lower())

    def status(self) -> dict:
        with self._lock:
            mc_sources = [source.copy() for source in self._sources if source["kind"] != "ftd"]
            ftd_sources = [source.copy() for source in self._sources if source["kind"] == "ftd"]
            if self._mc_available is None:
                self._mc_available = any(
                    path.endswith(".png")
                    and self._texture_key(f"{path.split('/')[1]}:{'/'.join(path.split('/')[3:])[:-4]}")
                    for path in self._assets
                    if "/textures/block/" in path
                )
            mc_available = bool(self._mc_available)
            minecraft = {
                "available": mc_available,
                "sources": mc_sources,
                "reasons": self._reasons["minecraft"].copy(),
            }
            ftd = {
                "available": bool(self._ftd),
                "sources": ftd_sources,
                "reasons": self._reasons["ftd"].copy(),
            }
            return {
                "available": mc_available or bool(self._ftd),
                "minecraft": minecraft,
                "ftd": ftd,
                "sources": [source.copy() for source in self._sources],
                "reasons": minecraft["reasons"] + ftd["reasons"],
            }

    def _discover_minecraft(self, root):
        vanilla = root / "versions/1.21.1/1.21.1.jar"
        clients = [vanilla] if vanilla.is_file() else []

        # Launchers often store the same client under an inherited version ID.
        # Only follow safe IDs whose chain identifies the pinned 1.21.1 client.
        def client(version, seen=()):
            if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,160}", version):
                return None
            if version in (".", "..") or version in seen or len(seen) >= 24:
                return None
            folder = root / "versions" / version
            doc = self._local_json(folder / (version + ".json"))
            pinned = (
                version == "1.21.1"
                or doc.get("downloads", {}).get("client", {}).get("sha1")
                == "30c73b1c5da787909b2f73340419fdf13b9def88"
            )
            if pinned:
                jar_id = doc.get("jar", version)
                if jar_id != version:
                    return client(jar_id, seen + (version,))
                path = folder / (version + ".jar")
                return path if path.is_file() else None
            return client(doc.get("inheritsFrom"), seen + (version,))

        for folder in sorted((root / "versions").glob("*"))[:256]:
            path = client(folder.name)
            if path and path not in clients:
                clients.append(path)
        paths = [(path, "vanilla") for path in clients]
        if not clients:
            self._reasons["minecraft"].append(
                "Minecraft 1.21.1 client JAR not found; import a local client JAR or resource-pack ZIP."
            )
        paths.extend((path, "mod") for path in sorted((root / "mods").glob("*.jar")))
        try:
            options = (root / "options.txt").read_text(encoding="utf-8")
            packs = json.loads(
                next(
                    line.split(":", 1)[1]
                    for line in options.splitlines()
                    if line.startswith("resourcePacks:")
                )
            )
        except (OSError, ValueError, StopIteration):
            packs = []
        if isinstance(packs, list):
            for pack in packs[:64]:
                if isinstance(pack, str) and pack.startswith("file/"):
                    relative = pack[5:]
                    if PurePosixPath(relative).name == relative and "\\" not in relative:
                        paths.append((root / "resourcepacks" / relative, "resourcepack"))
        for path, kind in paths:
            if not path.is_file():
                continue
            try:
                if path.stat().st_size > MAX_ARCHIVE_BYTES:
                    raise ValueError("archive exceeds 128 MiB")
                with path.open("rb") as stream:
                    content = stream.read(MAX_ARCHIVE_BYTES + 1)
                self._add_archive(content, path.name, kind)
            except (OSError, ValueError) as exc:
                self._reasons["minecraft"].append(f"{path.name}: {exc}")

    @staticmethod
    def _local_json(path):
        try:
            if path.stat().st_size > MAX_JSON_BYTES:
                return {}
            value = json.loads(path.read_bytes())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, UnicodeError, RecursionError):
            return {}

    def _discover_ftd(self, root):
        if root.name != "StreamingAssets" and (root / "From_The_Depths_Data/StreamingAssets").is_dir():
            root = root / "From_The_Depths_Data/StreamingAssets"
        core = root / "Mods/Core_Structural"
        if not core.is_dir():
            self._reasons["ftd"].append("From the Depths structural material definitions not found.")
            return
        definitions = {}
        for path in sorted((core / "Textures").glob("*.texture"))[:256]:
            texture = self._local_json(path)
            guid = texture.get("ComponentId", {}).get("Guid")
            if guid:
                definitions[guid] = texture
        aliases = {
            "metal mat": "metal",
            "wood mat": "wood",
            "stone mat": "stone",
            "alloy mat": "alloy",
            "lead mat": "lead",
            "rubber mat": "rubber",
            "heavy armour randomtile": "heavy armour",
            "glass mat": "glass",
            "simple glass mat": "glass",
        }
        missing = {}
        for path in sorted((core / "Materials").glob("*.material"))[:256]:
            material = self._local_json(path)
            name = material.get("ComponentId", {}).get("Name", "").lower()
            if name not in aliases:
                continue
            reference = material.get("ColorTextureReference", {})
            if not reference.get("IsValidReference"):
                continue
            texture = definitions.get(reference.get("Reference", {}).get("Guid"), {})
            relative = texture.get("FilenameOrUrl")
            if not isinstance(relative, str):
                continue
            try:
                relative = _member(relative)
            except ValueError:
                continue
            # Unity Resources paths are not necessarily loose files. Only serve a
            # bounded PNG that really exists under the installed asset roots.
            found = False
            for base in (root, core / "Assets", root / "Textures", root.parent / "Resources"):
                candidate = base / relative
                try:
                    if not candidate.is_relative_to(base) or not candidate.is_file():
                        continue
                    if candidate.stat().st_size > MAX_IMAGE_BYTES:
                        continue
                    content = candidate.read_bytes()
                    if not _png(content):
                        continue
                except OSError:
                    continue
                key = secrets.token_hex(16)
                self._images[key] = content
                self._ftd[aliases[name]] = key
                self._sources.append({"name": candidate.name, "kind": "ftd", "assets": 1})
                found = True
                break
            if not found:
                missing.setdefault(relative, []).append(aliases[name])
        if missing:
            from .ftd_textures import extract_base_colors

            extracted = extract_base_colors(root.parent, set(missing))
            loaded = 0
            for relative, content in extracted.items():
                if relative not in missing or not _png(content):
                    continue
                key = secrets.token_hex(16)
                self._images[key] = content
                for alias in missing.pop(relative):
                    self._ftd[alias] = key
                loaded += 1
            if loaded:
                self._sources.append(
                    {"name": "From the Depths Unity Resources", "kind": "ftd", "assets": loaded}
                )
        if missing:
            self._reasons["ftd"].append(
                "Referenced FtD color images could not be read from loose PNGs or Unity Resources: "
                + ", ".join(sorted(set(missing)))
            )
