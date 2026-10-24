"""Private conversion templates retain source identity and every sampled field."""

from dataclasses import fields, replace
from importlib import import_module

import numpy as np
import pytest

from fromthecraft.geometry import voxelize
from fromthecraft.model import Part, Scene, SourceRecord


@pytest.mark.parametrize("mode", [{}, {"detailed": True}, {"extreme": True}])
def test_compact_cells_share_only_identical_values_from_the_same_source(mode):
    record = SourceRecord("source-1", "cube", "block", ("Blueprint", "BLP", "0"), ())
    first = Part("wall", "box", (2, 1, 3), np.eye(4), "Metal", (0.5,) * 3, source_record=record)
    transform = np.eye(4)
    transform[0, 3] = 2
    second = replace(first, transform=transform, source_record=replace(record, id="source-2"))
    accent_transform = np.eye(4)
    accent_transform[:3, 3] = (0, 0.875, 0)
    accent = replace(first, identity="accent", size=(0.5, 0.125, 2), transform=accent_transform,
                     color=(0.1, 0.8, 0.8), decoration=True)
    source = Scene([first, second, accent], "blueprint")
    reference, offset = voxelize(source, scale=4, **mode)
    actual, actual_offset = voxelize(source, scale=4, compact=True, **mode)
    assert actual_offset == offset
    assert list(actual) == list(reference)
    for key, expected in reference.items():
        result = actual[key]
        for field in fields(Part):
            if field.name == "transform":
                np.testing.assert_array_equal(result.transform, expected.transform)
            elif field.name == "detail_sources":
                assert [(id(p), mask) for p, mask in result.detail_sources] == [
                    (id(p), mask) for p, mask in expected.detail_sources]
            else:
                assert getattr(result, field.name) == getattr(expected, field.name)
    assert len({id(part) for part in actual.values()}) < len(actual) // 3
    assert len({id(part) for part in reference.values()}) == len(reference)
    assert all(part.source_record is not second.source_record for key, part in actual.items() if key[0] < 8)
    assert first.shape == "box" and not first.detail_sources


def test_conversion_reuses_targets_for_shared_private_cells(monkeypatch):
    module = import_module("fromthecraft.convert")
    source = Scene([Part("wall", "box", (4, 2, 4), np.eye(4), "Stone", (0.5,) * 3)], "blueprint")
    expected = module.convert(source, "nbt", scale=2).content
    calls, target = 0, module.mc_target

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return target(*args, **kwargs)

    monkeypatch.setattr(module, "mc_target", counted)
    assert module.convert(source, "nbt", scale=2).content == expected
    assert calls == 1, "The 256 identical private cells need one immutable target state"
