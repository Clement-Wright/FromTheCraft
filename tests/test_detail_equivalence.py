"""Freeze fitter behavior before replacing sample-wise loops with bit operations."""

import numpy as np
import pytest

from fromthecraft.detail import DETAIL_SAMPLES, bits, fit_detail
from detail_reference import fit_detail as reference_fit


def test_fitter_optimization_preserves_exact_states_on_arbitrary_and_geometric_masks():
    rng = np.random.default_rng(682)
    samples = DETAIL_SAMPLES
    masks = [
        bits(rng.random(len(samples)) < density)
        for density in (0.001, 0.05, 0.3, 0.5, 0.9, 0.999)
        for _ in range(6)
    ]
    masks += [
        bits(samples[:, axis] < height) for axis in range(3) for height in (0.0625, 0.125, 0.1875, 0.5, 0.875)
    ]
    masks += [bits(samples[:, 1] + samples[:, 2] / length <= 1) for length in (1, 2, 3, 4)]
    masks += [0, (1 << len(samples)) - 1]
    for mask in masks:
        assert fit_detail(mask) == reference_fit(mask)


@pytest.mark.parametrize("extreme", [False, True])
def test_fitter_does_not_score_shapes_that_cannot_cover_the_source(extreme):
    from fromthecraft.extreme import fit_extreme

    class CountingMask(int):
        counts = 0

        def __and__(self, other):
            return CountingMask(int(self) & int(other))

        def __xor__(self, other):
            return CountingMask(int(self) ^ int(other))

        def bit_count(self):
            CountingMask.counts += 1
            return super().bit_count()

    fit = fit_extreme if extreme else fit_detail
    fit.cache_clear()
    mask = CountingMask(bits(np.arange(len(DETAIL_SAMPLES)) % 3 == 0))
    try:
        assert fit(mask) is None
        assert CountingMask.counts < 64, "Do not fully score hundreds of non-covering candidates"
    finally:
        fit.cache_clear()


def test_covering_pruning_preserves_states_including_all_dynamic_half_layer_pairs():
    from fromthecraft.detail import candidates, detail_choices, half_layer_options, VOLUME_MASK
    from fromthecraft.extreme import extra_candidates, fit_extreme

    masks = [mask for _, mask in (*candidates(), *extra_candidates())]
    for _, groups in half_layer_options():
        masks.extend(a | b for a in groups[0] for b in groups[1])
    masks.extend(bits(np.random.default_rng(i).random(len(DETAIL_SAMPLES)) < 0.4) for i in range(25))
    for mask in masks:
        assert fit_detail(mask) == reference_fit(mask)
        expected = min(
            (*extra_candidates(), *detail_choices(mask)),
            key=lambda item: ((mask & ~item[1]).bit_count(), ((mask ^ item[1]) & VOLUME_MASK).bit_count()),
        )[0]
        # The pre-optimization full-mask shortcut takes precedence over ties.
        assert fit_extreme(mask) == (None if mask == (1 << len(DETAIL_SAMPLES)) - 1 else expected)
