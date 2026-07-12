"""shiftab.plot — visualization for ShiftResult.

Headless-safe: forces the Agg backend before importing pyplot so this
module (and anything that imports shiftab) works in CI / server contexts
with no display.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .core import ShiftResult  # noqa: E402


def plot(
    self: ShiftResult,
    ax=None,
    show_zero: bool = True,
    band_color: str = "tab:blue",
    title: str = None,
):
    """Plot the shift function with its simultaneous confidence band.

    x-axis is in control-quantile units (0..1) for both methods. For
    ks_band a secondary top axis annotates the approximate control value
    at a sample of tick positions, since ks_band's native grid is raw
    control values.
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 5))

    order = np.argsort(self.quantiles)
    xq = self.quantiles[order]
    delta = self.delta[order]
    lower = self.lower[order]
    upper = self.upper[order]

    finite_vals = np.concatenate(
        [
            delta[np.isfinite(delta)],
            lower[np.isfinite(lower)],
            upper[np.isfinite(upper)],
        ]
    )
    if finite_vals.size == 0:
        finite_vals = np.array([0.0, 1.0])
    lo, hi = float(finite_vals.min()), float(finite_vals.max())
    span = hi - lo
    if span <= 0:
        span = max(abs(lo), 1.0)
    pad = 0.15 * span + 1e-9
    ylim_lo, ylim_hi = lo - pad, hi + pad

    lower_plot = np.where(np.isfinite(lower), lower, ylim_lo)
    upper_plot = np.where(np.isfinite(upper), upper, ylim_hi)

    ax.fill_between(
        xq,
        lower_plot,
        upper_plot,
        color=band_color,
        alpha=0.25,
        label=f"{int(round((1 - self.alpha) * 100))}% simultaneous band",
    )
    ax.plot(xq, delta, color=band_color, lw=2, label=r"$\hat\Delta$ (shift)")

    if show_zero:
        ax.axhline(0.0, color="black", lw=1, linestyle="--", label="no shift")

    for q0, q1 in self.significant_regions:
        ax.axvspan(q0, q1, color="red", alpha=0.15)

    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(ylim_lo, ylim_hi)
    ax.set_xlabel("control quantile")
    ax.set_ylabel(r"shift $\Delta$ = treatment $-$ control")
    ax.set_title(title or f"Shift function ({self.method}, n={self.n}, m={self.m})")
    ax.legend(loc="best", fontsize=9)

    if self.grid_type == "values":
        control_vals = self.grid[order]
        ticks = np.array([t for t in ax.get_xticks() if 0.0 <= t <= 1.0])
        if ticks.size:
            interp_vals = np.interp(ticks, xq, control_vals)
            secax = ax.secondary_xaxis("top")
            secax.set_xticks(ticks)
            secax.set_xticklabels([f"{v:.2g}" for v in interp_vals])
            secax.set_xlabel("approx. control value")

    return ax


ShiftResult.plot = plot
