"""Mask storage may share values, but source ownership and sampled output cannot change."""

from dataclasses import asdict, fields, replace
import hashlib
import json
import sys

import numpy as np
import pytest

from fromthecraft.geometry import voxelize
from fromthecraft.model import Part, Scene, SourceRecord, State


def panels():
    record = SourceRecord("panel-1", "box", "block", ("Blueprint", "0"), ())
    first = Part("panel", "box", (6, 0.5, 2), np.eye(4), "Metal", (0.8, 0.2, 0.1),
                 source_record=record)
    transform = np.eye(4)
    transform[0, 3] = 6
    second = replace(first, transform=transform, source_record=replace(record, id="panel-2"))
    return [first, second]


def test_repeated_partial_cells_share_masks_and_groups_within_each_source():
    sources = panels()

    def inspect_storage(cells):
        storage = sys._getframe(1).f_locals
        masks = list(storage["occupancy"].values())
        groups = list(storage["contributions"].values())
        assert len(cells) == 24
        assert len({mask for mask in masks}) == 1
        assert len({id(mask) for mask in masks}) == 1
        assert len({id(group) for group in groups}) == 2
        for position, group in storage["contributions"].items():
            ((owner, mask),) = group.values()
            assert owner is sources[position[0] // 6]
            assert mask is storage["occupancy"][position]
        return cells

    voxelize(Scene(sources, "blueprint"), extreme=True, cell_filter=inspect_storage)


def test_unique_mask_churn_stays_bounded_and_preserves_every_value(monkeypatch):
    import fromthecraft.geometry as geometry
    from fromthecraft.detail import DETAIL_SAMPLES

    # Supply many distinct sampled masks through the sampler boundary. Avoid
    # geometry queries and stop before fitting; this stresses live storage only.
    dimensions = (33, 10, 33)
    transform = np.eye(4)
    transform[:3, 3] = 0.125
    part = Part("varied surface", "box", (32, 9, 32), transform, "Stone", (0.5,) * 3)

    def sample_ids(batch, *_args):
        return np.ravel_multi_index(batch.T, dimensions)

    def sampled_masks(_shape, ids):
        result = np.zeros((len(ids), len(DETAIL_SAMPLES)), dtype=bool)
        result[:, :14] = (ids[:, None] >> np.arange(14)) & 1
        result[:, 4096] = True
        return result.ravel()

    monkeypatch.setattr(geometry, "_local_samples", sample_ids)
    monkeypatch.setattr(geometry, "contains", sampled_masks)

    class StorageInspected(Exception):
        pass

    def inspect_storage(cells):
        storage = sys._getframe(1).f_locals
        masks = storage["occupancy"]
        assert len(cells) == 10_890
        assert len(set(masks.values())) == len(cells)
        assert storage["intern_mask"].cache_info().currsize <= 8192
        assert len(storage["single_groups"]) <= 256
        for position, mask in masks.items():
            identifier = int(np.ravel_multi_index(position, dimensions))
            assert mask == (1 << 4096) | identifier
            ((owner, source_mask),) = storage["contributions"][position].values()
            assert owner is part and source_mask == mask
        raise StorageInspected

    with pytest.raises(StorageInspected):
        voxelize(Scene([part], "blueprint"), extreme=True, cell_filter=inspect_storage)


def sampled_snapshot(cells, sources):
    rows = []
    for position, part in cells.items():
        values = []
        for field in fields(Part):
            value = getattr(part, field.name)
            if field.name == "transform":
                value = value.tolist()
            elif field.name == "detail_sources":
                value = [(next(i for i, source in enumerate(sources) if source is owner), hex(mask))
                         for owner, mask in value]
            elif field.name == "detail_surface":
                value = hex(value)
            elif field.name in {"state", "mapping_override", "source_record"} and value is not None:
                value = asdict(value)
            values.append(value)
        rows.append((position, values))
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def overlapping_panels():
    sources = panels()
    # Later structural material must not take ownership of the first panel.
    sources.append(replace(sources[0], identity="overlap", color=(0.1, 0.8, 0.1),
                           mapping_override=State("minecraft:gold_block")))
    transform = np.eye(4)
    transform[:3, 3] = (0, 0.25, 0)
    accent = replace(sources[0], identity="accent", size=(2, 0.5, 1), transform=transform,
                     color=(0.1, 0.8, 0.9), decoration=True)
    sources.extend((accent, replace(accent, identity="repaint", color=(0.9, 0.1, 0.8)), accent))
    # Subsample features take the forward-seed path; they must stay independent.
    transform = np.eye(4)
    transform[:3, 3] = (2.125, 0.751, 0.125)
    sources.append(replace(accent, identity="tiny", size=(0.01, 0.01, 0.01), transform=transform))
    return sources


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("mode", [{}, {"detailed": True}, {"extreme": True}])
def test_shared_storage_preserves_every_sampled_field_for_overlays_and_seeds(compact, mode):
    sources = overlapping_panels()
    cells, offset = voxelize(Scene(sources, "blueprint"), compact=compact, **mode)
    assert offset == (0, 0, 0)
    expected = {
        # Frozen from 7424449 before changing mask/group allocation.
        "plain": "770e87bfb01966286d3f0a059181514b9672636b8fc11d836318f38c676ec6cc",
        "detailed": "73e3ddd80457a23c60269ad35cd3247501b41fade696583ab16e2927f479087d",
        "extreme": "aeeef33ec50b60c45005fefdbfa25f9fa24283ed5c8e8bca2526a50578a85c4a",
    }
    name = "extreme" if mode.get("extreme") else "detailed" if mode.get("detailed") else "plain"
    assert sampled_snapshot(cells, sources) == expected[name]
