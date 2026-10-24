"""Serialized detail shapes must cover hulls without inventing tall needles."""

from itertools import product

import numpy as np
import pytest

from fromthecraft.convert import convert
from fromthecraft.geometry import rotation
from fromthecraft.model import Part, Scene


def occupied(scene, points, offset):
    result = np.zeros(len(points), dtype=bool)
    for part in scene.parts:
        local = points - offset - part.transform[:3, 3]
        result |= np.all((local >= 0) & (local <= part.size), axis=1)
    return result


@pytest.mark.parametrize("size", [(0.125, 0.125, 0.125), (0.125, 1, 0.125), (1, 0.125, 0.125)])
def test_eighth_block_details_keep_their_real_extent_after_serialization(size):
    source = Scene([Part("tip", "box", size, np.eye(4), "Metal", (0.7, 0.1, 0.1))], "blueprint")
    result = convert(source, "nbt", mods=("copycats",), detailed_copycats=True)
    assert result.scene.parts
    lows = np.array([part.transform[:3, 3] for part in result.scene.parts]) + result.offset
    highs = np.array([part.transform[:3, 3] + part.size for part in result.scene.parts]) + result.offset
    np.testing.assert_allclose(lows.min(0), [0, 0, 0])
    np.testing.assert_allclose(highs.max(0), size)


@pytest.mark.parametrize("extreme", [False, True])
@pytest.mark.parametrize("orientation", range(24))
def test_thin_trim_near_a_lip_does_not_become_a_full_height_board(extreme, orientation):
    # Minimized from a Cygnus Wood down slope decoration: a thin skin along
    # one side of the cell occupies only its top quarter. A full-height board
    # has less volume than a half-height panel, but adds an exposed wall below.
    transform = np.eye(4)
    transform[:3, :3] = rotation(orientation)
    transform[:3, 3] = rotation(orientation) @ (0, 0.75, 0)
    source = Scene(
        [Part("lip trim", "box", (1 / 32, 0.25, 1), transform, "Metal", (0.8, 0.8, 0.8))], "blueprint"
    )
    result = convert(source, "nbt", mods=("copycats",), detailed_copycats=True, extreme_detail=extreme)
    output = []
    for part in result.scene.parts:
        corners = np.array(list(product(*[(0, extent) for extent in part.size])))
        world = corners @ part.transform[:3, :3].T + part.transform[:3, 3] + result.offset
        output.append(world @ rotation(orientation))
    points = np.concatenate(output)
    assert points[:, 1].min() >= 0.5 - 1e-8
    assert points[:, 1].max() <= 1 + 1e-8


@pytest.mark.parametrize("output", ["nbt", "litematic"])
@pytest.mark.parametrize("orientation", range(24))
def test_continuous_slope_has_no_holes_in_its_projected_hull(output, orientation):
    transform = np.eye(4)
    transform[:3, :3] = rotation(orientation)
    source = Scene(
        [Part("hull slope", "ftd_slope", (1, 1, 4), transform, "Metal", (0.7, 0.1, 0.1))],
        "blueprint",
    )
    result = convert(source, output, mods=("copycats",), detailed_copycats=True)
    # Every downward ray meets the original slope, including its very thin tip.
    # Query the reparsed exported boxes, rather than the fitter's sample masks.
    points = (
        np.array(list(product((0.25, 0.75), np.arange(0.03125, 1, 0.0625), (np.arange(64) + 0.5) / 16)))
        @ transform[:3, :3].T
    )
    hits = occupied(result.scene, points, result.offset).reshape(2, 16, 64).any(axis=1)
    assert hits.all(), f"Uncovered hull rays: {np.argwhere(~hits).tolist()}"


@pytest.mark.parametrize("orientation", range(24))
def test_triangular_hull_tip_cannot_become_a_full_height_needle(orientation):
    transform = np.eye(4)
    transform[:3, :3] = rotation(orientation)
    source = Scene(
        [Part("triangular tip", "ftd_corner_left", (1, 1, 4), transform, "Metal", (0.7, 0.1, 0.1))],
        "blueprint",
    )
    result = convert(source, "nbt", mods=("copycats",), detailed_copycats=True)
    tips = []
    for part in result.scene.parts:
        corners = np.array(list(product(*[(0, extent) for extent in part.size])))
        local = (corners + part.transform[:3, 3] + result.offset) @ transform[:3, :3]
        if local[:, 2].min() >= 3 - 1e-8:
            tips.append(local)
    assert tips
    # x + y + z/4 <= 1: the final cell's triangle is at most 1/4 wide/high.
    assert max(points[:, :2].max() for points in tips) <= 0.25 + 1e-8


@pytest.mark.parametrize(
    "family,length", [("ftd_square_left", 4), ("ftd_square_right", 3), ("ftd_offset_right_1", 2)]
)
def test_corner_hull_does_not_lose_its_exterior_between_projection_rays(family, length):
    source = Scene(
        [Part("corner wall", family, (1, 1, length), np.eye(4), "Metal", (0.7, 0.1, 0.1))],
        "blueprint",
    )
    result = convert(source, "nbt", mods=("copycats",), detailed_copycats=True)
    points = np.array(list(product((np.arange(16) + 0.5) / 16, repeat=3)))
    points[:, 2] *= length
    x, y, z = points.T
    # Independently written native halfspaces, including the 3m corner and
    # short offset transition seen in the Cygnus hull screenshots.
    inside = {
        "ftd_square_left": (y + z / 4 <= 1) & (x + y <= 1),
        "ftd_square_right": (y + z / 3 <= 1) & (y <= x),
        "ftd_offset_right_1": -x + y + z <= 1,
    }[family]
    assert occupied(result.scene, points[inside], result.offset).all()


def test_separate_corner_details_cannot_be_replaced_by_an_open_board_shell():
    transform = np.eye(4)
    transform[:3, 3] = 0.875
    source = Scene(
        [
            Part("low tip", "box", (0.125,) * 3, np.eye(4), "Metal", (0.7, 0.1, 0.1)),
            Part("high tip", "box", (0.125,) * 3, transform, "Metal", (0.7, 0.1, 0.1)),
        ],
        "blueprint",
    )
    result = convert(source, "nbt", mods=("copycats",), detailed_copycats=True)
    assert {part.identity for part in result.scene.parts} == {"copycats:copycat_byte"}
    # Include points on both sides of a board's 1/16 inner boundary.
    corner = np.array(list(product((0.03125, 0.09375), repeat=3)))
    points = np.concatenate((corner, corner + 0.875))
    assert occupied(result.scene, points, result.offset).all()
    assert not occupied(result.scene, np.array([[0.75, 0.25, 0.75]]), result.offset).any()
