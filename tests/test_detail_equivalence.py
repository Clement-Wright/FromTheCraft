"""Freeze fitter behavior before replacing sample-wise loops with bit operations."""

import numpy as np

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
