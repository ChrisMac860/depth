# shiftab — SPEC (architect: Claude Fable; implementers: subagents)

Shift-function A/B analysis: given a control sample and a treatment sample, estimate
HOW the treatment changed the whole distribution (effect at every quantile), with a
SIMULTANEOUS confidence band, so a user can see e.g. "median users improved, top-decile
users got worse" — information a mean/t-test A/B readout cannot show.

Method source: Doksum & Sievers (1976), "Plotting with Confidence: Graphical
Comparisons of Two Populations" (the dormant paper W4229715165).

## Repo layout (STRICT — two agents work in parallel in disjoint dirs)

```
shiftab/
  SPEC.md                  (this file — read-only for agents)
  src/shiftab/__init__.py  (Agent A)
  src/shiftab/core.py      (Agent A)
  src/shiftab/plot.py      (Agent A)
  src/shiftab/datasets.py  (Agent A)
  demo.py                  (Agent A)
  README.md                (Agent A)
  pyproject.toml           (Agent A — minimal, name=shiftab, src layout)
  tests/test_core.py       (Agent B)
  tests/test_edge_cases.py (Agent B)
  validation/run_validation.py  (Agent B)
  validation/scenarios.py       (Agent B)
```

Agent A must NOT write under tests/ or validation/. Agent B must NOT write under
src/ or the repo root. Python >=3.12, deps: numpy, scipy, matplotlib ONLY.

## Statistical contract

Control sample `x` (size n) ~ F, treatment sample `y` (size m) ~ G, both 1-D floats.

**Shift function:** Δ(t) = G⁻¹(F(t)) − t, evaluated at each sorted control value.
Interpretation: treatment ≈ control + Δ(control). Also expose the quantile view:
for q in a grid, Δ_q = Ĝ⁻¹(q) − F̂⁻¹(q).

**Method 1 — `method="ks_band"` (primary, distribution-free, simultaneous):**
Doksum–Sievers band by inverting the two-sample Kolmogorov–Smirnov acceptance region.

- d_α = c_α · sqrt((n + m) / (n · m)), with c_α = scipy.stats.kstwobign.ppf(1 − α).
- At each evaluation point t (use the sorted control values):
  - p = F̂_n(t) (empirical CDF of control at t)
  - lower index  h_L = ceil(m · (p − d_α));  upper index  h_U = floor(m · (p + d_α)) + 1
  - lower(t) = y_(h_L) − t  if 1 ≤ h_L ≤ m else −inf
  - upper(t) = y_(h_U) − t  if 1 ≤ h_U ≤ m else +inf
  (y_(k) = k-th order statistic of treatment, 1-indexed.)
- Index conventions differ by ±1 across references. The Monte Carlo coverage study
  (validation/) is the arbiter: the band must be SIMULTANEOUS at ≥ nominal − 2%.
  If coverage falls short, WIDEN the convention (never narrow it).

**Method 2 — `method="bootstrap"` (quantile-domain, sup-statistic simultaneous):**
- Quantile grid default: q = 0.05, 0.10, …, 0.95.
- Point estimate Δ_q as above (use `np.quantile(..., method="linear")`).
- B = 2000 bootstrap resamples (resample x and y independently with replacement);
  compute Δ_q* on each; se_q = std over bootstrap. Simultaneous band via the
  sup-t (max-|t|) method: T* = max_q |Δ_q* − Δ̂_q| / se_q, c = (1−α) quantile of T*,
  band = Δ̂_q ± c·se_q. Guard se_q == 0 (ties/discrete) by flooring se at a tiny eps
  and flagging those grid points.
- Must accept a `rng: np.random.Generator | int | None` argument for determinism.

## API contract (Agent B writes tests against EXACTLY this)

```python
from shiftab import shift_analysis, ShiftResult

res = shift_analysis(
    control, treatment,
    alpha=0.05,
    method="ks_band",          # or "bootstrap"
    quantile_grid=None,         # bootstrap only; default np.arange(0.05, 0.951, 0.05)
    n_boot=2000,                # bootstrap only
    rng=None,                   # int seed, Generator, or None
)
```

`ShiftResult` (dataclass) fields:
- `method: str`, `alpha: float`, `n: int`, `m: int`
- `grid: np.ndarray`     — evaluation points (control values for ks_band; quantiles for bootstrap)
- `grid_type: str`       — "values" | "quantiles"
- `delta: np.ndarray`    — point estimate of the shift at each grid point
- `lower, upper: np.ndarray` — simultaneous (1−α) band (may contain ±inf for ks_band)
- `quantiles: np.ndarray`    — F̂_n(grid) for ks_band (so both methods can report per-quantile)
- `significant_regions: list[tuple[float, float]]` — maximal contiguous QUANTILE
  intervals where the band excludes 0 (lower > 0 or upper < 0)
- `any_significant: bool`
- `mean_diff: float`, `median_shift: float`
- `welch_p: float`, `ks_p: float` (context stats via scipy)
- `summary() -> str`  — human-readable digest
- `plot(ax=None, show_zero=True, band_color=..., title=...) -> matplotlib Axes`
  (implemented in plot.py, attached to the dataclass; x-axis in QUANTILE units with
  a secondary readable annotation of values; shaded band, Δ̂ line, zero line,
  significant regions highlighted)

Input validation: raise ValueError on n or m < 10, NaNs/inf in data, non-1-D input,
alpha outside (0, 0.5]. Ties and integer/discrete data are ALLOWED.

`datasets.py`: `make_ab(scenario: str, n: int, m: int, rng) -> (control, treatment)`
with scenarios: "null" (identical), "location" (+0.3σ), "scale" (×1.3, mean-matched),
"tail_gain" (top 15% of treatment scaled ×1.5, lognormal base),
"mean_neutral_tail" (top 10% inflated, rest deflated so E[treatment]==E[control],
computed analytically not empirically), "revenue" (zero-inflated lognormal, realistic
A/B: 92% zeros control, 91.5% zeros treatment, slight lognormal shift).

## PRE-REGISTERED PASS/FAIL GATES (QA runs these; verdict is binary)

G1 COVERAGE (validity of the band):
   ks_band, alpha=0.05, scenarios null-normal, null-lognormal, null-poisson(λ=3, heavy
   ties): (n,m) ∈ {(100,100), (500,500), (200,800)}; 1000 reps each.
   PASS iff simultaneous coverage (band contains Δ=0 everywhere) ≥ 93% in ALL cells.
   bootstrap, same design but 500 reps, (n,m) ∈ {(200,200), (500,500)}: ≥ 91%.

G2 FALSE-ALARM on the product output:
   Under the same null cells, fraction of reps with any_significant == True must be
   ≤ 7% (ks_band) / ≤ 9% (bootstrap) in every cell.

G3 LOCATION SANITY:
   "location" (δ = 0.3σ), n=m=1000, 500 reps, ks_band: detection (any_significant)
   ≥ 90%, and mean over reps of median(Δ̂) within δ ± 0.1σ.

G4 PRODUCT CLAIM (the reason this tool exists):
   "mean_neutral_tail", n=m=5000, 300 reps, ks_band: detection ≥ 70% while Welch
   t-test rejects in ≤ 10% of the same reps. (Shift plot sees what the t-test can't.)

G5 ENGINEERING:
   All unit tests pass; demo.py runs end-to-end producing demo_output/*.png without
   error; ks_band on n=m=100_000 completes < 5 s; deterministic given rng=int.

VERDICT = PASS iff G1–G5 all pass. Any gate failing after one debugging iteration
(fix must not weaken a gate) ⇒ FAIL, with a written diagnosis.

Validation harness must write `validation/results.json` (machine-readable per-cell
numbers) and print a per-gate table. Runtime budget for the full validation run:
≤ 15 minutes on a laptop; choose vectorization accordingly (the ks_band path is pure
order statistics — vectorize with numpy, no Python loops over reps' inner grid).
