# shiftab

Shift-function A/B analysis: instead of collapsing an A/B test to a single
mean difference, estimate how the treatment changed the *whole distribution*
— with a simultaneous confidence band — so you can see things like "median
users improved, top-decile users got worse." Method: Doksum & Sievers (1976),
*"Plotting with Confidence: Graphical Comparisons of Two Populations."*

## Install

```bash
pip install -e .
```

(deps: `numpy`, `scipy`, `matplotlib`; Python >= 3.12)

## Usage

```python
from shiftab import shift_analysis

res = shift_analysis(control, treatment, alpha=0.05, method="ks_band")

print(res.summary())
print(res.any_significant, res.significant_regions)

ax = res.plot(title="My A/B test")
ax.figure.savefig("shift.png")
```

### Methods

- `method="ks_band"` (default, primary): distribution-free simultaneous band
  from inverting the two-sample Kolmogorov-Smirnov acceptance region.
  Vectorized with numpy; fast even at n=m=100,000.
- `method="bootstrap"`: quantile-domain sup-t simultaneous band over a
  quantile grid (default 0.05..0.95 step 0.05), via `n_boot` resamples.
  Accepts `rng` (`int | np.random.Generator | None`) for determinism.

### `ShiftResult` fields

`method, alpha, n, m, grid, grid_type, delta, lower, upper, quantiles,
significant_regions, any_significant, mean_diff, median_shift, welch_p,
ks_p`, plus `.summary()` and `.plot(ax=None, show_zero=True, band_color=...,
title=...)`.

`grid_type` is `"values"` for `ks_band` (grid = sorted control values) or
`"quantiles"` for `bootstrap` (grid = the quantile grid itself); `quantiles`
always gives the per-point quantile so both methods report comparably.
`significant_regions` is a list of contiguous `(q_start, q_end)` quantile
intervals where the band excludes 0.

## Synthetic datasets

`shiftab.datasets.make_ab(scenario, n, m, rng)` generates six scenarios for
demoing/testing: `"null"`, `"location"`, `"scale"`, `"tail_gain"`,
`"mean_neutral_tail"` (the flagship case: mean unchanged, tail moved —
analytically constructed, not curve-fit), and `"revenue"` (zero-inflated).

## Demo

```bash
cd shiftab
python demo.py
```

Generates a `mean_neutral_tail` A/B pair, runs both methods, prints a
summary contrasting Welch's t-test (fails to reject) against shiftab's
detection in the tail, and saves `demo_output/shift_ks_band.png` and
`demo_output/shift_bootstrap.png`.

## Statistical contract

See `SPEC.md` at the repo root for the full frozen contract (exact index
conventions, band formulas, validation rules, and the pre-registered
QA gates).
