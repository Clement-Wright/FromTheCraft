import numpy as np
import pytest

from fromthecraft.mesh_geometry import MeshSampler, is_closed


def test_sampling_continues_beyond_the_former_budget():
    sampler = MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False)
    sampler.work = 200_000_000
    assert sampler.contains([[1 / 3, 1 / 3, 1 / 3]]).tolist() == [True]


def test_sampling_retains_a_finite_budget():
    sampler = MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False)
    sampler.work = 20_000_000_000
    with pytest.raises(ValueError, match="Decorative mesh sampling budget exceeded"):
        sampler.contains([[1 / 3, 1 / 3, 1 / 3]])


def test_sampling_can_be_cancelled_after_crossing_the_former_budget():
    from fromthecraft.model import Cancelled

    sampler = MeshSampler(np.eye(3), np.array([[0, 1, 2]]), cancelled=lambda: True)
    sampler.work = 200_000_000
    with pytest.raises(Cancelled):
        sampler.contains([[1 / 3, 1 / 3, 1 / 3]])


def test_large_surface_seed_plan_can_start_and_be_cancelled():
    from fromthecraft.mesh_geometry import surface_seeds
    from fromthecraft.model import Cancelled, Part

    part = Part(
        "large sheet", "mesh", (1, 1, 1), np.diag([1000.0, 1000.0, 1000.0, 1.0]),
        "Metal", (0.5, 0.5, 0.5), mesh=(np.eye(3), np.array([[0, 1, 2]]), False, 0.125),
    )
    cancelled = False
    seeds = surface_seeds(part, 1, lambda: cancelled)
    assert next(seeds).shape == (3,)
    cancelled = True
    with pytest.raises(Cancelled):
        for _ in seeds:
            pass


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


@pytest.mark.parametrize("detailed", [False, True])
def test_mesh_inside_an_already_filled_cell_does_not_repeat_containment(monkeypatch, detailed):
    from fromthecraft.geometry import voxelize
    from fromthecraft.mesh_geometry import prepare_meshes
    from fromthecraft.model import Part, Scene

    solid = Part("first material", "box", (1, 1, 1), np.eye(4), "Metal", (0.5, 0.5, 0.5))
    mesh = Part(
        "inside decoration", "mesh", (1, 1, 1), np.eye(4), "Glass", (0.1, 0.8, 0.9),
        mesh=(np.eye(3) * 0.5 + 0.25, np.array([[0, 1, 2]])), decoration=True,
    )
    original = MeshSampler.contains
    tested_points = 0

    def counted_contains(self, points):
        nonlocal tested_points
        tested_points += len(points)
        return original(self, points)

    monkeypatch.setattr(MeshSampler, "contains", counted_contains)
    scene = prepare_meshes(Scene([solid, mesh], "blueprint"), "decorations", 0.125, 1)
    cells, offset = voxelize(scene, detailed=detailed)
    assert len(cells) == 1
    assert offset == (0, 0, 0)
    assert cells[(0, 0, 0)].identity == "first material"
    assert cells[(0, 0, 0)].shape == "box"
    assert tested_points == 0


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("thickness", [0.0625, 0.125, 0.25, 0.5])
def test_mesh_occupancy_is_exactly_equal_to_original_at_boundaries_and_batch_seams(closed, thickness):
    from mesh_reference import ReferenceMeshSampler

    rng = np.random.default_rng(4813)
    vertices = rng.normal(size=(72, 3)) * (0.001, 4, 100) + (-10, 0.5, 3)
    indices = np.arange(72).reshape(-1, 3)
    points = rng.uniform(vertices.min(0) - 1, vertices.max(0) + 1, (33000, 3))
    triangles = vertices[indices]
    centers = triangles.mean(axis=1)
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    boundary = np.concatenate(
        [centers + normals * distance for distance in (0, thickness / 2, thickness / 2 - 1e-10,
                                                       thickness / 2 + 1e-10)]
    )
    points = np.concatenate((points, vertices, centers, boundary))
    expected = ReferenceMeshSampler(vertices, indices, thickness, closed=closed).contains(points)
    actual = MeshSampler(vertices, indices, thickness, closed=closed).contains(points)
    np.testing.assert_array_equal(actual, expected)


def test_repeated_sampling_reuses_triangle_normals(monkeypatch):
    vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
    sampler = MeshSampler(vertices, np.array([[0, 1, 2]]), closed=False)
    assert sampler.contains([[0.25, 0.25, 0.05]]).tolist() == [True]
    original = np.cross
    recalculations = 0

    def counted_cross(*args, **kwargs):
        nonlocal recalculations
        recalculations += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(np, "cross", counted_cross)
    for _ in range(3):
        assert sampler.contains([[0.25, 0.25, 0.05]]).tolist() == [True]
    assert recalculations == 0


@pytest.mark.parametrize("closed", [False, True])
def test_surface_seed_batches_preserve_every_original_point_and_order(closed):
    from mesh_reference import reference_surface_seeds
    from fromthecraft.mesh_geometry import surface_seed_batches
    from fromthecraft.model import Part

    part = Part(
        "sheet", "mesh", (1, 1, 1), np.diag([-4.0, 1.0, 8.0, 1.0]), "Metal", (0.5, 0.5, 0.5),
        mesh=(np.eye(3), np.array([[0, 1, 2], [2, 1, 0]]), closed, 0.125),
    )
    expected = np.asarray(list(reference_surface_seeds(part, 2)))
    batches = list(surface_seed_batches(part, 2))
    assert all(len(batch) == 4096 for batch in batches[:-1])
    assert 0 < len(batches[-1]) <= 4096
    np.testing.assert_array_equal(np.concatenate(batches), expected)
