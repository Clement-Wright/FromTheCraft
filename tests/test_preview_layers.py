from dataclasses import replace

import numpy as np

from fromthecraft.model import Part, Scene
from fromthecraft.preview import preview


def test_coincident_decorations_keep_their_own_render_layer():
    host = Part("hull", "box", (1, 1, 1), np.eye(4), "Stone", (1, 1, 1))
    decal = replace(host, identity="decal", color=(0, 1, 1), decoration=True)
    model = preview(Scene([host, decal], "blueprint"))
    assert len(model["groups"]) == 2
    assert [group["decoration"] for group in model["groups"]] == [False, True]
    assert sum(len(group["matrices"]) for group in model["groups"]) == 32
