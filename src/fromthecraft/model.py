from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

MAX_PARTS = 500_000
MAX_VOLUME = 8_000_000
MAX_AXIS = 2048
DATA_VERSION = 3955


@dataclass(frozen=True)
class State:
    name: str
    properties: tuple[tuple[str, str], ...] = ()
    copied_material: "State | None" = None
    copied_materials: tuple[tuple[str, "State"], ...] = ()


@dataclass(frozen=True)
class SourceRecord:
    id: str
    type_key: str
    kind: str
    path: tuple[str, ...]
    parent_path: tuple[str, ...]
    host_id: str | None = None
    name: str = ""
    hide_host: bool = False
    geometry_status: str = "resolved"


@dataclass
class Part:
    identity: str
    shape: str
    size: tuple[float, float, float]
    transform: np.ndarray
    material: str
    color: tuple[float, float, float]
    transparent: bool = False
    state: State | None = None
    source_cell: tuple[int, int, int] | None = None
    material_slot: str | None = None
    source_record: SourceRecord | None = None
    mapping_override: State | None = None
    mapping_full: bool = False
    mesh: tuple | None = None
    decoration: bool = False
    replaces_host: bool = False


@dataclass
class Scene:
    parts: list[Part]
    format: str
    notices: Counter = field(default_factory=Counter)
    version: str = ""
    source_hash: str = ""
    source_records: tuple[SourceRecord, ...] = ()


@dataclass
class Result:
    content: bytes
    scene: Scene
    format: str
    offset: tuple[float, float, float]
    notices: Counter


class Cancelled(ValueError):
    pass


Progress = Callable[[float], None]
