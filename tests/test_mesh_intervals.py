"""Certified packet classifications preserve literal scalar predicates and work."""

import numpy as np
import pytest

from fromthecraft import mesh_geometry as mesh

native = pytest.importorskip("fromthecraft._mesh_native")


def test_native_interval_feature_is_advertised_for_older_binary_compatibility():
    assert getattr(native, "INTERVAL_PACKETS", 0) == 1


@pytest.mark.parametrize("packet", [16, 128, 512, 2048])
@pytest.mark.parametrize("exponent", [-550, -50, 0, 50, 520])
def test_certified_packet_queries_match_original_scalar_bits_and_budget(packet, exponent):
    rng = np.random.default_rng(5291)
    multiplier = np.exp2(float(exponent))
    vertices = rng.uniform(-3, 3, (180, 3)) * multiplier
    points = rng.uniform(-3, 3, (4096, 3)) * multiplier
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        sampler = mesh.MeshSampler(vertices, np.arange(180).reshape(-1, 3), closed=True)
        arrays = sampler._native_arrays()
    points[:180] = sampler.triangles.reshape(-1, 3)
    points[180:185] = ((np.nan, 0, 0), (0, np.inf, 0), (0, 0, -np.inf), (0, -0.0, 0),
                       (np.nextafter(0.0, 1.0), 0, 0))
    expected = native.contains(points, *arrays, True, .0625)
    assert native.contains(points, *arrays, True, .0625, packet) == expected


@pytest.mark.parametrize("interval_available", [False, True])
@pytest.mark.parametrize("optimized", [False, True])
def test_only_supported_optimized_closed_meshes_use_wider_packets(monkeypatch, interval_available, optimized):
    from fromthecraft.geometry import voxelize
    from fromthecraft.model import Part, Scene

    monkeypatch.setattr(native, "INTERVAL_PACKETS", int(interval_available), raising=False)
    vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    part = Part("solid", "mesh", (1, 1, 1), np.diag([4., 4., 4., 1.]), "Metal", (.5, .5, .5),
                mesh=(vertices, faces, True, .125, np.ones(3)))
    observed = []
    original = mesh.MeshSampler.contains

    def record(self, points):
        observed.append(self.packet_size)
        return original(self, points)

    monkeypatch.setattr(mesh.MeshSampler, "contains", record)
    voxelize(Scene([part], "blueprint"), detailed=True, optimized=optimized)
    expected = (2048 if interval_available else 128) if optimized else 0
    assert observed and set(observed) == {expected}
