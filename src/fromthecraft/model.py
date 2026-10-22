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


@dataclass
class Scene:
    parts: list[Part]
    format: str
    notices: Counter = field(default_factory=Counter)
    version: str = ""


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
