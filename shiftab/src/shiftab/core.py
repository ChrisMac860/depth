"""shiftab.core — shift-function A/B analysis (Doksum & Sievers, 1976).

Implements the two methods from SPEC.md:
  - "ks_band": distribution-free simultaneous band from inverting the
    two-sample Kolmogorov-Smirnov acceptance region.
  - "bootstrap": quantile-domain sup-t simultaneous band.

All arrays returned on ShiftResult are numpy arrays. See SPEC.md at the
repo root for the frozen statistical / API contract this module implements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np
from scipy import stats

__all__ = ["shift_analysis", "ShiftResult"]

_VALID_METHODS = ("ks_band", "bootstrap")


@dataclass
class ShiftResult:
    method: str
    alpha: float
    n: int
    m: int

    grid: np.ndarray
    grid_type: str  # "values" | "quantiles"

    delta: np.ndarray
    lower: np.ndarray
    upper: np.ndarray

    quantiles: np.ndarray

    significant_regions: list
    any_significant: bool

    mean_diff: float
    median_shift: float

    welch_p: float
    ks_p: float

    # populated by plot.py at import time (attached to the class, not
    # instances) — declared here only so static tools see the attribute.
    plot = None  # type: ignore[assignment]

    def summary(self) -> str:
        lines = []
        lines.append(
            f"shiftab shift_analysis  method={self.method}  alpha={self.alpha}  "
            f"n={self.n}  m={self.m}"
        )
        lines.append(
            f"mean_diff={self.mean_diff:.4f}   median_shift={self.median_shift:.4f}"
        )
        lines.append(
            f"Welch t-test p={self.welch_p:.4g}   KS two-sample p={self.ks_p:.4g}"
        )
        if self.any_significant:
            regions_str = ", ".join(
                f"[{a:.2f}, {b:.2f}]" for a, b in self.significant_regions
            )
            lines.append(
                f"SIGNIFICANT shift in quantile region(s): {regions_str} "
                f"(band excludes 0 at {int((1 - self.alpha) * 100)}% simultaneous confidence)"
            )
        else:
            lines.append(
                f"No significant shift detected - the {int((1 - self.alpha) * 100)}% "
                "simultaneous band contains 0 at every evaluated quantile."
            )
        if self.delta.size:
            idx = int(np.argmax(np.abs(self.delta)))
            lines.append(
                f"Largest |shift|: Delta={self.delta[idx]:.4f} at control quantile "
                f"{self.quantiles[idx]:.2f}"
            )
        return "\n".join(lines)


def _normalize_rng(rng) -> np.random.Generator:
    if isinstance(rng, np.random.Generator):
        return rng
    return np.random.default_rng(rng)


def _validate_inputs(control, treatment, alpha, method, quantile_grid) -> tuple:
    control = np.asarray(control, dtype=float)
    treatment = np.asarray(treatment, dtype=float)

    if control.ndim != 1:
        raise ValueError(f"control must be 1-D, got shape {control.shape}")
    if treatment.ndim != 1:
        raise ValueError(f"treatment must be 1-D, got shape {treatment.shape}")

    n, m = control.size, treatment.size
    if n < 10:
        raise ValueError(f"control sample size n={n} < 10 (minimum required)")
    if m < 10:
        raise ValueError(f"treatment sample size m={m} < 10 (minimum required)")

    if not np.all(np.isfinite(control)):
        raise ValueError("control contains NaN or inf values")
    if not np.all(np.isfinite(treatment)):
        raise ValueError("treatment contains NaN or inf values")

    if not (0 < alpha <= 0.5):
        raise ValueError(f"alpha must be in (0, 0.5], got {alpha}")

    if method not in _VALID_METHODS:
        raise ValueError(f"method must be one of {_VALID_METHODS}, got {method!r}")

    if quantile_grid is not None:
        qg = np.asarray(quantile_grid, dtype=float)
        if qg.ndim != 1 or qg.size == 0:
            raise ValueError("quantile_grid must be a non-empty 1-D array")
        if not np.all(np.isfinite(qg)) or np.any(qg <= 0) or np.any(qg >= 1):
            raise ValueError("quantile_grid entries must lie strictly in (0, 1)")

    return control, treatment


def _find_significant_regions(sig_mask: np.ndarray, quantiles: np.ndarray) -> list:
    """Maximal contiguous runs of True in sig_mask -> (q_start, q_end) tuples."""
    regions = []
    n = sig_mask.size
    i = 0
    while i < n:
        if sig_mask[i]:
            j = i
            while j + 1 < n and sig_mask[j + 1]:
                j += 1
            regions.append((float(quantiles[i]), float(quantiles[j])))
            i = j + 1
        else:
            i += 1
    return regions


def _ks_band(control: np.ndarray, treatment: np.ndarray, alpha: float):
    n = control.size
    m = treatment.size

    x_sorted = np.sort(control)
    y_sorted = np.sort(treatment)

    c_alpha = stats.kstwobign.ppf(1.0 - alpha)
    d_alpha = c_alpha * np.sqrt((n + m) / (n * m))

    i = np.arange(1, n + 1, dtype=float)
    p = i / n  # F_hat_n(t) at each sorted control point, vectorized

    h_L = np.ceil(m * (p - d_alpha)).astype(np.int64)
    h_U = np.floor(m * (p + d_alpha)).astype(np.int64) + 1

    valid_L = (h_L >= 1) & (h_L <= m)
    valid_U = (h_U >= 1) & (h_U <= m)

    idx_L = np.clip(h_L - 1, 0, m - 1)
    idx_U = np.clip(h_U - 1, 0, m - 1)

    lower = np.where(valid_L, y_sorted[idx_L] - x_sorted, -np.inf)
    upper = np.where(valid_U, y_sorted[idx_U] - x_sorted, np.inf)

    # Point estimate of the shift function: G_hat^{-1}(F_hat(t)) - t, using
    # linear-interpolated empirical quantiles of treatment (vectorized).
    # Interpolate directly off y_sorted (already computed above) instead of
    # calling np.quantile again, which would re-sort treatment internally —
    # this matters at n=m=100k (G5's <5s budget).
    pos = p * (m - 1)
    lo_idx = np.floor(pos).astype(np.int64)
    hi_idx = np.ceil(pos).astype(np.int64)
    frac = pos - lo_idx
    q_vals = y_sorted[lo_idx] + (y_sorted[hi_idx] - y_sorted[lo_idx]) * frac
    delta = q_vals - x_sorted

    grid = x_sorted
    quantiles = p

    sig_mask = (lower > 0) | (upper < 0)
    regions = _find_significant_regions(sig_mask, quantiles)

    return grid, "values", delta, lower, upper, quantiles, regions


def _bootstrap_band(
    control: np.ndarray,
    treatment: np.ndarray,
    alpha: float,
    quantile_grid: Optional[np.ndarray],
    n_boot: int,
    rng: np.random.Generator,
):
    if quantile_grid is None:
        q = np.round(np.arange(0.05, 0.951, 0.05), 10)
    else:
        q = np.asarray(quantile_grid, dtype=float)

    n = control.size
    m = treatment.size

    delta_hat = np.quantile(treatment, q, method="linear") - np.quantile(
        control, q, method="linear"
    )

    idx_x = rng.integers(0, n, size=(n_boot, n))
    idx_y = rng.integers(0, m, size=(n_boot, m))
    xb = control[idx_x]  # (n_boot, n)
    yb = treatment[idx_y]  # (n_boot, m)

    qx = np.quantile(xb, q, axis=1, method="linear")  # (len(q), n_boot)
    qy = np.quantile(yb, q, axis=1, method="linear")  # (len(q), n_boot)
    boot_deltas = (qy - qx).T  # (n_boot, len(q))

    se = boot_deltas.std(axis=0, ddof=1)
    se = np.where(se < 1e-12, 1e-12, se)

    T = np.max(np.abs(boot_deltas - delta_hat) / se, axis=1)
    c = np.quantile(T, 1.0 - alpha, method="linear")

    lower = delta_hat - c * se
    upper = delta_hat + c * se

    grid = q
    quantiles = q

    sig_mask = (lower > 0) | (upper < 0)
    regions = _find_significant_regions(sig_mask, quantiles)

    return grid, "quantiles", delta_hat, lower, upper, quantiles, regions


def shift_analysis(
    control,
    treatment,
    alpha: float = 0.05,
    method: str = "ks_band",
    quantile_grid=None,
    n_boot: int = 2000,
    rng: Union[int, np.random.Generator, None] = None,
) -> ShiftResult:
    """Estimate the shift function G^{-1}(F(t)) - t with a simultaneous band.

    See SPEC.md for the full statistical contract.
    """
    control, treatment = _validate_inputs(control, treatment, alpha, method, quantile_grid)
    n, m = control.size, treatment.size

    if method == "ks_band":
        grid, grid_type, delta, lower, upper, quantiles, regions = _ks_band(
            control, treatment, alpha
        )
    else:  # "bootstrap"
        rng_ = _normalize_rng(rng)
        grid, grid_type, delta, lower, upper, quantiles, regions = _bootstrap_band(
            control, treatment, alpha, quantile_grid, n_boot, rng_
        )

    mean_diff = float(np.mean(treatment) - np.mean(control))
    median_shift = float(np.median(treatment) - np.median(control))

    welch_p = float(stats.ttest_ind(control, treatment, equal_var=False).pvalue)
    ks_p = float(stats.ks_2samp(control, treatment).pvalue)

    return ShiftResult(
        method=method,
        alpha=alpha,
        n=n,
        m=m,
        grid=grid,
        grid_type=grid_type,
        delta=delta,
        lower=lower,
        upper=upper,
        quantiles=quantiles,
        significant_regions=regions,
        any_significant=bool(len(regions) > 0),
        mean_diff=mean_diff,
        median_shift=median_shift,
        welch_p=welch_p,
        ks_p=ks_p,
    )
