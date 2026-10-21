import numpy as np

from fromthecraft.model import Part, Scene, State
from fromthecraft.preview import preview


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
