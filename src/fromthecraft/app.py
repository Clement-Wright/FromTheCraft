import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.formparsers import MultiPartException

from .convert import convert, read_file
from .ftd import CATALOG_INFO
from .model import Cancelled, Result, Scene
from .preview import preview
from .textures import TextureLibrary, MAX_ARCHIVE_BYTES
from .compatibility import mod_choices, selected_mods
from .edits import EditLayer
from .projects import export_project, import_project

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="conversion")
sessions = OrderedDict()
sessions_lock = threading.Lock()
STATIC = Path(__file__).with_name("static")
shutdown_callback = None


@dataclass
class Session:
    textures: TextureLibrary | None = None
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    lock: threading.RLock = field(default_factory=threading.RLock)
    cancelled: threading.Event = field(default_factory=threading.Event)
    generation: int = 0
    source: Scene | None = None
    source_bytes: bytes = b""
    edits: EditLayer | None = None
    filename: str = "structure"
    state: str = "empty"
    progress: float = 0
    error: str = ""
    result: Result | None = None
    converted: dict | None = None
    result_id: str = ""
    touched: float = field(default_factory=time.monotonic)

    def invalidate(self, state="stale"):
        self.cancelled.set()
        self.cancelled = threading.Event()
        self.generation += 1
        self.result = None
        self.converted = None
        self.result_id = ""
        self.state = state
        self.error = ""
        self.progress = 0


def session_for(request):
    with sessions_lock:
        session = sessions.get(request.cookies.get("fromthecraft"))
        if session is None:
            raise HTTPException(401, "Session expired. Reload the page.")
        session.touched = time.monotonic()
        return session


@app.middleware("http")
async def local_service(request, call_next):
    if request.method not in {"GET", "HEAD"}:
        limit = MAX_ARCHIVE_BYTES + 1024**2 if request.url.path == "/api/textures" else 33 * 1024**2
        if int(request.headers.get("content-length", "0")) > limit:
            return Response("Upload exceeds the local file limit", status_code=413)
        incoming, exceeded = 0, False
        receive = request._receive

        async def bounded_receive():
            nonlocal incoming, exceeded
            message = await receive()
            incoming += len(message.get("body", b""))
            if incoming > limit:
                exceeded = True
                raise MultiPartException("Upload exceeds the local file limit")
            return message

        request._receive = bounded_receive
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return Response("Only this local application may submit files", status_code=403)
        try:
            session = session_for(request)
        except HTTPException as exc:
            return Response(exc.detail, status_code=exc.status_code)
        if not secrets.compare_digest(request.headers.get("x-fromthecraft-token", ""), session.token):
            return Response("Invalid local session token", status_code=403)
    response = await call_next(request)
    if request.method not in {"GET", "HEAD"} and exceeded:
        response = Response("Upload exceeds the local file limit", status_code=413)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'"
    )
    return response


@app.get("/api/session")
def open_session(request: Request, response: Response):
    with sessions_lock:
        sid = request.cookies.get("fromthecraft")
        session = sessions.get(sid)
        if session is None:
            if len(sessions) >= 4:
                _, oldest = sessions.popitem(last=False)
                oldest.cancelled.set()
            sid = secrets.token_urlsafe(24)
            session = sessions[sid] = Session()
        response.set_cookie("fromthecraft", sid, httponly=True, samesite="strict")
    with session.lock:
        if session.textures is None:
            session.textures = TextureLibrary()
    return {
        "token": session.token,
        "can_close": shutdown_callback is not None,
        "ftd_catalog": CATALOG_INFO["version"],
        "ftd_catalog_entries": CATALOG_INFO["entries"],
        "mod_choices": mod_choices(),
        "textures": session.textures.status(),
    }


@app.get("/api/textures/{key}")
def texture_image(request: Request, key: str, token: str = ""):
    session = session_for(request)
    if not secrets.compare_digest(token, session.token):
        raise HTTPException(403, "Invalid local session token")
    try:
        return Response(session.textures.image(key), media_type="image/png")
    except KeyError as exc:
        raise HTTPException(404, "Texture not found") from exc


@app.post("/api/textures")
async def texture_archive(request: Request, file: UploadFile = File(...)):
    session = session_for(request)
    content = await file.read(MAX_ARCHIVE_BYTES + 1)
    await file.close()
    try:
        await run_in_threadpool(session.textures.add_archive, content, file.filename or "textures.zip")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with session.lock:
        source, result, generation = session.source, session.result, session.generation
    source_display = await run_in_threadpool(preview, source, (0, 0, 0), session.textures) if source else None
    converted = (
        await run_in_threadpool(preview, result.scene, result.offset, session.textures) if result else None
    )
    with session.lock:
        if generation != session.generation:
            raise HTTPException(409, "Source or conversion changed while loading textures")
        session.converted = converted
    return {"source": source_display, "converted": converted, "textures": session.textures.status()}


@app.get("/api/heartbeat")
def heartbeat(request: Request):
    session_for(request)
    return {"running": True}


@app.post("/api/close")
def close_app():
    if shutdown_callback is None:
        raise HTTPException(409, "Stop this development service in its terminal")
    shutdown_callback()
    return {"state": "closed"}


@app.post("/api/source")
async def open_source(request: Request, file: UploadFile = File(...)):
    session = session_for(request)
    with session.lock:
        session.invalidate("loading")
        generation = session.generation
        session.source = None
        session.edits = None
        session.source_bytes = b""
    content = await file.read(32 * 1024**2 + 1)
    await file.close()
    if len(content) > 32 * 1024**2:
        with session.lock:
            if generation == session.generation:
                session.state, session.error = "failed", "File exceeds 32 MiB"
        raise HTTPException(413, "File exceeds 32 MiB")
    try:
        scene = await run_in_threadpool(read_file, content, Path(file.filename or "").suffix)
        display = await run_in_threadpool(preview, scene, (0, 0, 0), session.textures)
    except ValueError as exc:
        with session.lock:
            if generation == session.generation:
                session.state, session.error = "failed", str(exc)
        raise HTTPException(400, str(exc)) from exc
    with session.lock:
        if generation != session.generation:
            raise HTTPException(409, "A newer source replaced this file")
        session.source = scene
        session.source_bytes = content
        session.edits = EditLayer(scene)
        session.filename = Path(file.filename or "structure").stem
        session.state = "loaded"
    return {
        "source": display,
        "notices": dict(scene.notices),
        "filename": session.filename,
        "edits": session.edits.snapshot(),
    }


@app.get("/api/edits")
def edit_status(request: Request):
    session = session_for(request)
    with session.lock:
        return {"edits": session.edits.snapshot() if session.edits else None}


def change_edits(session, command=None, direction=None):
    with session.lock:
        if session.edits is None:
            raise HTTPException(409, "Open a source file first")
        try:
            changed = getattr(session.edits, direction)() if direction else session.edits.apply(command)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if changed:
            session.invalidate()
        return {"edits": session.edits.snapshot(), "invalidated": changed}


@app.post("/api/edits")
def edit_source(request: Request, command: dict):
    return change_edits(session_for(request), command)


@app.post("/api/edits/undo")
def undo_source(request: Request):
    return change_edits(session_for(request), direction="undo")


@app.post("/api/edits/redo")
def redo_source(request: Request):
    return change_edits(session_for(request), direction="redo")


class Options(BaseModel):
    model_config = {"extra": "forbid"}
    format: Literal["nbt", "litematic", "blueprint"]
    scale: Literal[0.25, 0.5, 1, 2, 4] = 1
    preference: Literal["balanced", "material", "color"] = "balanced"
    detailed_copycats: bool = False
    decoration_mode: Literal["structure", "decorations", "appearance"] = "structure"
    surface_thickness: Literal[0.0625, 0.125, 0.25, 0.5] = 0.125
    hollow: bool = False
    shell_thickness: Literal[1, 2, 3, 4] = 1
    mods: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("mods")
    @classmethod
    def known_mods(cls, value):
        selected_mods(value)
        return value


def checked_settings(settings, scene, layer):
    options = Options.model_validate(settings)
    if options.format not in ({"nbt", "litematic"} if scene.format == "blueprint" else {"blueprint"}):
        raise ValueError("Project output must target the other game")
    from .compatibility import MODS

    enabled = selected_mods(options.mods)
    allowed = {b["name"] for slug in enabled for b in MODS[slug]["blocks"]}
    for command in layer.commands:
        mapping = command.get("mapping")
        if mapping and not mapping["name"].startswith("minecraft:") and mapping["name"] not in allowed:
            raise ValueError("Project mapping requires a disabled mod: " + mapping["name"])
    return options.model_dump()


@app.post("/api/project/save")
def save_project(request: Request, document: dict):
    session = session_for(request)
    with session.lock:
        if session.source is None:
            raise HTTPException(409, "Open a source file first")
        try:
            settings = checked_settings(document.get("settings", {}), session.source, session.edits)
            view = document.get("view", {})
            if not isinstance(view, dict):
                raise ValueError("Invalid view settings")
            return export_project(session.source, session.edits, session.filename, settings, view)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.post("/api/project/open")
def open_project(request: Request, document: dict):
    session = session_for(request)
    with session.lock:
        if session.source is None:
            raise HTTPException(409, "Open the original source file before its project")
        try:
            layer, settings, view = import_project(document, session.source)
            settings = checked_settings(settings, session.source, layer)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        session.edits = layer
        session.invalidate()
        return {"edits": layer.snapshot(), "settings": settings, "view": view}


@app.get("/api/palette")
def palette(request: Request, mods: str = ""):
    session_for(request)
    from .compatibility import BUILDING_BLOCKS, MOD_STATES, MODS
    from .palettes import BLOCKS

    try:
        enabled = selected_mods([m for m in mods.split(",") if m])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    entries = []
    owners = {b["name"]: slug for slug, mod in MODS.items() for b in mod["blocks"]}
    for name, block in sorted(BUILDING_BLOCKS.items()):
        owner = block.get("mod", owners.get(name, "vanilla"))
        if owner not in ("vanilla", *enabled):
            continue
        rules = MOD_STATES.get(name)
        if rules is None:
            rules = {}
            for rule in BLOCKS.get(name, {}).get("states", []):
                values = rule.get("values")
                if rule["type"] == "bool":
                    values = ["false", "true"]
                if values:
                    rules[rule["name"]] = [str(v) for v in values]
        entries.append({**block, "mod": owner, "states": rules})
    return {"blocks": entries}


@app.post("/api/preset/save")
def save_preset(request: Request, document: dict):
    session = session_for(request)
    with session.lock:
        if session.source is None:
            raise HTTPException(409, "Open a source file first")
        try:
            settings = checked_settings(document.get("settings", {}), session.source, session.edits)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        types = {}
        for key, record in session.edits.records.items():
            types.setdefault(record.type_key, []).append(session.edits.mappings.get(key))
        mappings = [
            {"type_key": key, "mapping": values[0]}
            for key, values in sorted(types.items())
            if values[0] is not None and all(v == values[0] for v in values)
        ]
        return {"schema": 1, "kind": "fromthecraft-preset", "settings": settings, "type_mappings": mappings}


@app.post("/api/preset/open")
def open_preset(request: Request, document: dict):
    session = session_for(request)
    with session.lock:
        if session.source is None:
            raise HTTPException(409, "Open a source file first")
        try:
            if (
                document.get("schema") != 1
                or document.get("kind") != "fromthecraft-preset"
                or set(document) - {"schema", "kind", "settings", "type_mappings"}
            ):
                raise ValueError("Unsupported preset schema")
            mappings = document.get("type_mappings", [])
            if not isinstance(mappings, list) or len(mappings) > 1000:
                raise ValueError("Invalid preset mappings")
            clone = export_project(session.source, session.edits, session.filename, {}, {})
            layer, _, _ = import_project(clone, session.source)
            types = {record.type_key for record in layer.records.values()}
            skipped = 0
            for item in mappings:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"type_key", "mapping"}
                    or not isinstance(item["type_key"], str)
                ):
                    raise ValueError("Invalid preset type mapping")
                if item["type_key"] not in types:
                    skipped += 1
                    continue
                layer.apply({"kind": "mapping", "type_keys": [item["type_key"]], "mapping": item["mapping"]})
            settings = checked_settings(document.get("settings", {}), session.source, layer)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        session.edits = layer
        session.invalidate()
        return {"edits": layer.snapshot(), "settings": settings, "skipped_types": skipped}


@app.post("/api/palette/preview")
def palette_preview(request: Request, mapping: dict):
    from .model import Part, SourceRecord, State
    from .palettes import mc_material
    import numpy as np

    session = session_for(request)
    record = SourceRecord("thumbnail", "thumbnail", "block", (), ())
    material, color = mc_material(mapping.get("name", ""))
    scene = Scene(
        [Part("thumbnail", "cube", (1, 1, 1), np.eye(4), material, color, source_record=record)], "nbt"
    )
    try:
        layer = EditLayer(scene)
        layer.apply({"kind": "mapping", "ids": ["thumbnail"], "mapping": mapping})
        state = layer.derive(scene).parts[0].mapping_override
        scene.parts[0].state = State(state.name, state.properties)
        scene.parts[0].identity = state.name
        return preview(scene, textures=session.textures)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/convert")
def start_conversion(request: Request, options: Options):
    session = session_for(request)
    with session.lock:
        if session.source is None:
            raise HTTPException(409, "Open a source file first")
        session.invalidate("working")
        generation, cancelled = session.generation, session.cancelled
        scene = session.edits.derive(session.source) if session.edits else session.source

    def progress(value):
        with session.lock:
            if generation == session.generation:
                session.progress = value

    def work():
        try:
            result = convert(
                scene,
                options.format,
                options.scale,
                options.preference,
                progress,
                cancelled.is_set,
                options.hollow,
                options.shell_thickness,
                options.mods,
                options.detailed_copycats,
                options.decoration_mode,
                options.surface_thickness,
            )
            display = preview(result.scene, result.offset, session.textures)
            with session.lock:
                if generation == session.generation and not cancelled.is_set():
                    session.result, session.converted = result, display
                    session.result_id = secrets.token_urlsafe(16)
                    session.state, session.progress = "ready", 1
        except (ValueError, Cancelled) as exc:
            with session.lock:
                if generation == session.generation:
                    session.state, session.error = "failed", str(exc)
        except Exception:
            import logging

            logging.exception("Conversion failed")
            with session.lock:
                if generation == session.generation:
                    session.state, session.error = (
                        "failed",
                        "Conversion failed. See the application log for details.",
                    )

    executor.submit(work)
    return {"state": "working"}


@app.get("/api/status")
def status(request: Request):
    session = session_for(request)
    with session.lock:
        payload = {"state": session.state, "progress": session.progress, "error": session.error}
        if session.result:
            result = session.result
            payload.update(
                converted=session.converted,
                result_id=session.result_id,
                offset=result.offset,
                sha256=hashlib.sha256(result.content).hexdigest(),
                notices=dict(result.notices),
                filename=session.filename + "_converted." + result.format,
            )
        return payload


@app.post("/api/invalidate")
def invalidate(request: Request):
    session = session_for(request)
    with session.lock:
        session.invalidate()
    return {"state": "stale"}


@app.post("/api/cancel")
def cancel(request: Request):
    session = session_for(request)
    with session.lock:
        session.invalidate("cancelled")
    return {"state": "cancelled"}


@app.get("/api/export")
def export(request: Request, result_id: str = ""):
    session = session_for(request)
    with session.lock:
        if session.result is None or result_id != session.result_id:
            raise HTTPException(409, "Convert again before exporting")
        filename = "".join(c for c in session.filename if c.isalnum() or c in "-_ ")[:80] or "structure"
        filename += f"_converted.{session.result.format}"
        fallback = "".join(c for c in filename if c.isascii()) or "structure"
        return Response(
            session.result.content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
            },
        )


@app.get("/")
def index():
    if not (STATIC / "index.html").exists():
        raise HTTPException(503, "Build the frontend first: cd ui && npm ci && npm run build")
    return FileResponse(STATIC / "index.html")


if (STATIC / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
