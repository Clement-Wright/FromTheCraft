"""Optional coherent queries and early hollow fitting preserve complete exports."""

import importlib

import numpy as np
import pytest

from fromthecraft.compatibility import MODS
from fromthecraft.convert import convert
from fromthecraft.model import Cancelled, Part, Scene


def decorated_scene():
    wall = Part("wall", "box", (2, 1, 2), np.eye(4), "Metal", (0.8, 0.8, 0.8))
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    transform = np.eye(4)
    transform[:3, 3] = (0.2, 0.95, -0.2)
    decal = Part(
        "decal",
        "mesh",
        (1, 1, 1),
        transform,
        "Metal",
        (0.1, 0.8, 0.9),
        mesh=(vertices, np.array([[0, 1, 2]])),
        decoration=True,
    )
    return Scene([wall, decal], "blueprint")


@pytest.mark.parametrize("scale", [0.5, 1, 2, 3])
@pytest.mark.parametrize("detail", ["plain", "detailed", "extreme"])
def test_optimized_complete_export_matches_original(scale, detail):
    scene = decorated_scene()
    options = dict(
        scale=scale,
        mods=tuple(MODS),
        preference="color",
        decoration_mode="appearance",
        detailed_copycats=detail == "detailed",
        extreme_detail=detail == "extreme",
    )
    expected = convert(scene, "nbt", **options)
    actual = convert(scene, "nbt", optimized_conversion=True, **options)
    assert actual.content == expected.content
    assert actual.offset == expected.offset
    assert actual.notices == expected.notices


def test_optimized_without_native_keeps_portable_original_output(monkeypatch):
    import fromthecraft.mesh_geometry as mesh

    monkeypatch.setattr(mesh, "_mesh_native", None)
    scene = decorated_scene()
    options = dict(mods=("create", "copycats"), extreme_detail=True, decoration_mode="decorations")
    assert (
        convert(scene, "nbt", optimized_conversion=True, **options).content
        == convert(scene, "nbt", **options).content
    )


@pytest.mark.parametrize("thickness", [1, 2])
def test_optimized_hollow_skips_fitting_interior_and_keeps_neighbor_masks(monkeypatch, thickness):
    import fromthecraft.extreme as extreme

    scene = Scene([Part("hull", "box", (5, 5, 5), np.eye(4), "Stone", (1, 1, 1))], "blueprint")
    options = dict(hollow=True, shell_thickness=thickness, mods=("create", "copycats"), extreme_detail=True)
    expected = convert(scene, "nbt", **options)
    real, fits = extreme.fit_extreme, []

    def fitted(mask):
        fits.append(mask)
        return real(mask)

    monkeypatch.setattr(extreme, "fit_extreme", fitted)
    actual = convert(scene, "nbt", optimized_conversion=True, **options)
    assert actual.content == expected.content
    assert actual.offset == expected.offset and actual.notices == expected.notices
    assert len(fits) == 125 - (5 - thickness * 2) ** 3


def test_optimized_hollow_cache_preserves_notice_and_shell_setting():
    from fromthecraft.conversion_cache import GeometryCache

    scene = Scene([Part("hull", "box", (5, 5, 5), np.eye(4), "Stone", (1, 1, 1))], "blueprint")
    options = dict(
        hollow=True, optimized_conversion=True, geometry_cache=GeometryCache(), geometry_key="ship"
    )
    first = convert(scene, "nbt", **options)
    second = convert(scene, "nbt", **options)
    assert first.content == second.content and first.notices == second.notices
    thicker = convert(scene, "nbt", shell_thickness=2, **options)
    assert thicker.content != first.content
    assert not scene.notices, "Hollowing must not mutate the source or pollute later conversions"


def test_optimized_cancellation_stays_available():
    with pytest.raises(Cancelled):
        convert(decorated_scene(), "nbt", optimized_conversion=True, cancelled=lambda: True)


def test_optimized_mesh_uses_packet_kernel(monkeypatch):
    native = pytest.importorskip("fromthecraft._mesh_native")
    real, packets = native.contains, []

    def track(*args):
        packets.append(args[7] if len(args) == 8 else 0)
        return real(*args)

    monkeypatch.setattr(native, "contains", track)
    convert(
        decorated_scene(),
        "nbt",
        mods=("create", "copycats"),
        decoration_mode="decorations",
        detailed_copycats=True,
        optimized_conversion=True,
    )
    assert packets and all(width == 128 for width in packets)


def test_optimized_hollow_cancellation_during_topology(monkeypatch):
    module = importlib.import_module("fromthecraft.convert")
    original = module.hollow_cells
    cancelled = False

    def hollow(*args, **kwargs):
        nonlocal cancelled
        cancelled = True
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "hollow_cells", hollow)
    with pytest.raises(Cancelled):
        convert(decorated_scene(), "nbt", hollow=True, optimized_conversion=True, cancelled=lambda: cancelled)
