from itertools import product
import numpy as np
import pytest
from fromthecraft.model import State, Scene, Part
from fromthecraft.copycats import geometry_boxes
from fromthecraft.minecraft import write_structure, read_structure, write_litematic, read_litematic
from fromthecraft.geometry import voxelize
from fromthecraft.detail import fit_detail, bits, DETAIL_SAMPLES


def original_states():
    for axis in "xyz":
        yield State("copycats:copycat_beam", (("axis", axis),))
    for side in ("up", "down", "east", "west", "north", "south"):
        yield State("copycats:copycat_board", ((side, "true"),))
    for axis, half in product(("x", "z"), ("bottom", "top")):
        yield State(
            "copycats:copycat_half_layer",
            (("axis", axis), ("half", half), ("negative_layers", "2"), ("positive_layers", "7")),
        )
    for facing in ("north", "south", "east", "west"):
        for family in ("vertical_half_layer", "stacked_half_layer"):
            yield State(
                "copycats:copycat_" + family,
                (("facing", facing), ("negative_layers", "3"), ("positive_layers", "6")),
            )
        yield State("copycats:copycat_vertical_step", (("facing", facing),))
        for family in ("slice", "vertical_slice", "corner_slice"):
            for n in (1, 3, 7):
                yield State("copycats:copycat_" + family, (("facing", facing), ("layers", str(n))))


@pytest.mark.parametrize("state", list(original_states()))
@pytest.mark.parametrize(
    "writer,reader", [(write_structure, read_structure), (write_litematic, read_litematic)]
)
def test_additional_copycats_roundtrip_materials_and_only_occupied_boxes(state, writer, reader):
    from dataclasses import replace

    state = replace(state, copied_material=State("minecraft:red_concrete"))
    scene = reader(writer({(0, 0, 0): state}, (1, 1, 1)))
    assert not scene.notices
    expected = geometry_boxes(state)
    assert len(scene.parts) == len(expected)
    assert all(part.state == state for part in scene.parts)
    assert all(part.color[0] > part.color[1] for part in scene.parts)
    for part, (_, box) in zip(scene.parts, expected):
        np.testing.assert_allclose(part.transform[:3, 3], box[:3])
        np.testing.assert_allclose(part.size, np.asarray(box[3:]) - box[:3])


def test_independent_beam_board_and_half_layer_dimensions():
    for axis in "xyz":
        box = geometry_boxes(State("copycats:copycat_beam", (("axis", axis),)))[0][1]
        assert np.prod(np.asarray(box[3:]) - box[:3]) == 0.25
        assert box["xyz".index(axis)] == 0
        assert box["xyz".index(axis) + 3] == 1
    box = geometry_boxes(State("copycats:copycat_board", (("south", "true"),)))[0][1]
    assert box == (0, 0, 15 / 16, 1, 1, 1)
    boxes = geometry_boxes(
        State(
            "copycats:copycat_half_layer", (("axis", "z"), ("negative_layers", "2"), ("positive_layers", "7"))
        )
    )
    assert dict(boxes) == {
        "negative_layers": (0, 0, 0, 1, 0.25, 0.5),
        "positive_layers": (0, 0, 0.5, 1, 0.875, 1),
    }


def test_beam_and_thin_board_are_fitting_candidates_without_full_block_substitution():
    for target in [
        State("copycats:copycat_beam", (("axis", "z"),)),
        State("copycats:copycat_board", (("south", "true"),)),
    ]:
        occupied = np.zeros(len(DETAIL_SAMPLES), dtype=bool)
        for _, box in geometry_boxes(target):
            occupied |= np.all((DETAIL_SAMPLES >= box[:3]) & (DETAIL_SAMPLES < box[3:]), axis=1)
        fitted = fit_detail(bits(occupied))
        assert fitted is not None
        assert fitted.name == target.name


def test_source_full_box_does_not_turn_into_a_detail_shape():
    part = Part("wall", "box", (1, 1, 1), np.eye(4), "Metal", (0.6, 0.1, 0.1))
    cells, _ = voxelize(Scene([part], "blueprint"), detailed=True)
    assert cells[(0, 0, 0)].shape == "box"
