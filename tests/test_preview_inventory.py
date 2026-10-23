import numpy as np

from fromthecraft.model import Part, Scene, State
from fromthecraft.preview import preview


def test_preview_reports_missing_target_faces_separately_from_ftd_availability():
    from fromthecraft.textures import TextureLibrary
    from test_textures import archive, cube, png

    textures = TextureLibrary(discover=False)
    textures.add_archive(
        archive(
            {"assets/example/models/block/red.json": cube(), "assets/example/textures/block/red.png": png()}
        ),
        "mod.jar",
    )
    state = State("copycats:copycat_layer", copied_material=State("example:red"))
    part = Part(state.name, "box", (1, 0.5, 1), np.eye(4), "Metal", (0.5, 0.5, 0.5), state=state)
    display = preview(Scene([part], "nbt"), textures=textures)
    assert display["texture_coverage"] == {"resolved_faces": 6, "missing_faces": 0, "missing_blocks": []}
    missing = preview(
        Scene([Part("example:missing", "box", (1, 1, 1), np.eye(4), "Metal", (0.5, 0.5, 0.5))], "nbt"),
        textures=textures,
    )
    assert missing["texture_coverage"]["missing_faces"] == 6
    assert missing["texture_coverage"]["missing_blocks"] == ["example:missing"]


def test_instance_metadata_matches_order_and_inventory_counts_block_types():
    parts = []
    for x, facing in enumerate(["north", "south", "north"]):
        matrix = np.eye(4)
        matrix[0, 3] = x
        parts.append(
            Part(
                "minecraft:oak_stairs",
                "stairs",
                (1, 1, 1),
                matrix,
                "Wood",
                (0.6, 0.4, 0.2),
                state=State("minecraft:oak_stairs", (("facing", facing),)),
            )
        )
    display = preview(Scene(parts, "nbt"), (10, 0, 0))
    group = display["groups"][0]
    records = [display["blocks"][index] for index in group["block_indices"]]
    assert [record["properties"]["facing"] for record in records] == ["north", "south", "north"]
    assert len(display["blocks"]) == 2
    assert group["matrices"][12] == 10
    assert display["materials"] == [
        {"name": "minecraft:oak_stairs", "material": "Wood", "properties": {}, "count": 3}
    ]


def test_source_inventory_counts_full_beams_as_parts_not_voxels():
    part = Part("Metal beam (4m)", "box", (1, 1, 4), np.eye(4), "Metal", (0.4, 0.4, 0.4))
    display = preview(Scene([part], "blueprint"))
    assert display["materials"][0]["count"] == 1
    assert display["blocks"][0]["name"] == "Metal beam (4m)"


def test_mixed_copycat_bytes_count_one_exported_host_block():
    from fromthecraft.minecraft import read_structure, write_structure

    state = State(
        "copycats:copycat_byte",
        (("bottom_northwest", "true"), ("top_southeast", "true")),
        copied_materials=(
            ("bottom_northwest", State("minecraft:red_concrete")),
            ("top_southeast", State("minecraft:glass")),
        ),
    )
    display = preview(read_structure(write_structure({(0, 0, 0): state}, (1, 1, 1))))
    assert display["count"] == 2
    assert len(display["materials"]) == 1
    assert display["materials"][0]["count"] == 1
    assert len(display["materials"][0]["copied_materials"]) == 2
    assert {block["copied_material"]["name"] for block in display["blocks"]} == {
        "minecraft:red_concrete",
        "minecraft:glass",
    }
