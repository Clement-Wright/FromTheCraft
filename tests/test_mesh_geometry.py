import numpy as np

from fromthecraft.mesh_geometry import MeshSampler, is_closed


def test_tetrahedron_is_a_solid_and_open_sheet_is_not_filled():
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    assert is_closed(vertices, faces)
    sampler = MeshSampler(vertices, faces)
    points = np.random.default_rng(32).uniform(0, 1, (10000, 3))
    expected = points.sum(axis=1) <= 1
    np.testing.assert_array_equal(sampler.contains(points), expected)
    assert abs(sampler.contains(points).mean() - 1 / 6) < 0.01
    sheet = MeshSampler(vertices[:3], np.array([[0, 1, 2]]), thickness=0.125)
    assert not sheet.closed
    np.testing.assert_array_equal(
        sheet.contains(np.array([[0.2, 0.2, 0.01], [0.2, 0.2, 0.2], [0.9, 0.9, 0.0]])), [True, False, False]
    )


def test_duplicate_vertex_seams_still_form_closed_solids():
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    duplicated = vertices[faces].reshape(-1, 3)
    assert is_closed(duplicated, np.arange(12).reshape(-1, 3))


def test_grid_aligned_open_sheet_covers_its_whole_plane_after_voxelization():
    from fromthecraft.model import Part, Scene
    from fromthecraft.mesh_geometry import prepare_meshes
    from fromthecraft.geometry import voxelize

    vertices = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], dtype=float)
    transform = np.diag([10.0, 1.0, 10.0, 1.0])
    part = Part(
        "sheet",
        "mesh",
        (1, 1, 1),
        transform,
        "Metal",
        (0.5, 0.5, 0.5),
        mesh=(vertices, np.array([[0, 1, 2], [0, 2, 3]])),
        decoration=True,
    )
    cells, offset = voxelize(prepare_meshes(Scene([part], "blueprint"), "decorations", 0.125, 1))
    coverage = {(int(p[0] + offset[0]), int(p[2] + offset[2])) for p in cells}
    assert {(x, z) for x in range(10) for z in range(10)} <= coverage
    world_cells = {tuple(int(p[i] + offset[i]) for i in range(3)) for p in cells}
    assert {(x, y, z) for x in range(10) for y in (-1, 0) for z in range(10)} <= world_cells
