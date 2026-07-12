"""DEPTH engine — thin, faithful wrapper around the `shiftab` library.

Responsibilities (see SPEC.md "shiftab reuse" + "API contract" sections):
  1. Robustly locate and `sys.path.insert` the `shiftab` library (it lives in
     a sibling repo directory; we do NOT vendor/copy it).
  2. Call `shiftab.shift_analysis` with the exact statistics untouched (G2:
     the web layer must not alter the numbers).
  3. Serialize the result into the frozen JSON response shape, with every
     non-finite float (±inf, NaN) converted to `None` (JSON null) so the
     wire format is always valid JSON, and downsample `curve` to <=400
     points while preserving both endpoints and the max-|delta| point.

This module owns zero Flask/HTTP concerns — `app.py` calls `analyze()` and
turns ValueError into a 400 response.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

# ---------------------------------------------------------------------------
# 1. Locate and import shiftab
# ---------------------------------------------------------------------------


def _shiftab_src_candidates() -> Iterable[Path]:
    here = Path(__file__).resolve()
    # Primary, spec-given path: depth/server/engine.py -> parents[2] is the
    # repo root (SleepingBeauts), sibling of shiftab/.
    yield here.parents[2] / "shiftab" / "src"
    # Fallback: walk upward from this file looking for a shiftab/src dir,
    # in case the depth/ directory is relocated relative to shiftab/.
    for parent in here.parents:
        yield parent / "shiftab" / "src"


def _find_shiftab_src() -> Path:
    seen = set()
    for candidate in _shiftab_src_candidates():
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "shiftab" / "__init__.py").is_file():
            return candidate
    raise RuntimeError(
        "Could not locate the shiftab library (looked for a shiftab/src/"
        "shiftab/__init__.py, searching upward from "
        f"{Path(__file__).resolve()}). Expected shiftab/ as a sibling of the "
        "depth/ repo root — see SPEC.md 'shiftab reuse'."
    )


_SHIFTAB_SRC = _find_shiftab_src()
if str(_SHIFTAB_SRC) not in sys.path:
    sys.path.insert(0, str(_SHIFTAB_SRC))

try:
    import shiftab  # noqa: E402
    from shiftab import shift_analysis  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment problem, not logic
    raise RuntimeError(
        f"shiftab library found at {_SHIFTAB_SRC} but failed to import: {exc}"
    ) from exc


# ---------------------------------------------------------------------------
# 2. Reproducibility note (spec ambiguity resolved)
# ---------------------------------------------------------------------------
# shift_analysis() accepts an `rng` for the bootstrap method. The API contract
# has no rng field in the request, and the project principle (see repo-root
# CLAUDE.md) is "re-runs are idempotent". We therefore seed with a fixed
# constant rather than OS entropy, so POST /api/analyze is deterministic for
# identical inputs (including bootstrap). ks_band is exact/deterministic
# regardless and ignores rng entirely.
_FIXED_RNG_SEED = 42

MAX_CURVE_POINTS = 400


# ---------------------------------------------------------------------------
# 3. Sanitization helpers
# ---------------------------------------------------------------------------


def _finite_or_none(x: Any) -> Optional[float]:
    """Cast to a plain Python float, or None if not finite (±inf/NaN)."""
    try:
        fx = float(x)
    except (TypeError, ValueError):
        return None
    return fx if math.isfinite(fx) else None


def sanitize_for_json(obj: Any) -> Any:
    """Recursively replace any non-finite float (incl. numpy scalars) with
    None, and coerce numpy scalar types to plain Python types. Belt-and-
    suspenders pass applied once more in app.py before jsonify, on top of
    the field-level sanitization already done when building the response.
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return _finite_or_none(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


# ---------------------------------------------------------------------------
# 4. Curve downsampling
# ---------------------------------------------------------------------------


def _downsample_indices(n: int, max_points: int, must_keep: Iterable[int]) -> list[int]:
    """Choose <=max_points indices from range(n), evenly spaced along the
    axis, always including every index in `must_keep` (e.g. both endpoints
    and the argmax-|delta| point).
    """
    must_keep = set(int(i) for i in must_keep)
    if n <= max_points:
        return list(range(n))

    base = np.linspace(0, n - 1, max_points)
    idx_set = set(int(round(v)) for v in base)
    idx_set |= must_keep

    if len(idx_set) > max_points:
        removable = sorted(idx_set - must_keep)
        excess = len(idx_set) - max_points
        if removable and excess > 0:
            positions = np.linspace(0, len(removable) - 1, excess)
            to_remove = {removable[int(round(p))] for p in positions}
            idx_set -= to_remove

    return sorted(idx_set)


# ---------------------------------------------------------------------------
# 5. Public entry point
# ---------------------------------------------------------------------------


def analyze(
    control,
    treatment,
    alpha: float = 0.05,
    method: str = "ks_band",
    n_boot: int = 2000,
    quantile_grid=None,
) -> dict:
    """Run shiftab.shift_analysis and serialize to the frozen response shape
    from SPEC.md's "API contract" / POST /api/analyze section.

    Raises ValueError on invalid input (mirrors shiftab's own validation) —
    app.py catches this and turns it into an HTTP 400.
    """
    result = shift_analysis(
        control,
        treatment,
        alpha=alpha,
        method=method,
        quantile_grid=quantile_grid,
        n_boot=n_boot,
        rng=_FIXED_RNG_SEED,
    )

    quantiles = np.asarray(result.quantiles, dtype=float)
    delta = np.asarray(result.delta, dtype=float)
    lower_raw = np.asarray(result.lower, dtype=float)
    upper_raw = np.asarray(result.upper, dtype=float)

    # "value" = control-side value at each quantile. ks_band's grid IS
    # already control values (grid_type == "values"); bootstrap's grid is
    # the quantile axis itself, so compute the empirical control quantile.
    if result.grid_type == "values":
        value = np.asarray(result.grid, dtype=float)
    else:
        value = np.quantile(np.asarray(control, dtype=float), quantiles, method="linear")

    # significant per point, computed from the FULL raw (pre-null) arrays,
    # BEFORE downsampling — same formula shiftab uses internally to build
    # significant_regions, so it stays consistent with that field.
    sig_mask = (lower_raw > 0) | (upper_raw < 0)

    # Sort ascending by q (defensive — both methods already produce
    # increasing quantile arrays, but the contract requires it explicitly).
    order = np.argsort(quantiles, kind="stable")
    quantiles = quantiles[order]
    delta = delta[order]
    lower_raw = lower_raw[order]
    upper_raw = upper_raw[order]
    value = value[order]
    sig_mask = sig_mask[order]

    n_points = quantiles.size
    if n_points == 0:
        argmax_idx = 0
        must_keep: list[int] = []
    else:
        abs_delta = np.abs(delta)
        argmax_idx = int(np.nanargmax(abs_delta)) if np.any(np.isfinite(abs_delta)) else 0
        must_keep = [0, n_points - 1, argmax_idx]

    keep_idx = _downsample_indices(n_points, MAX_CURVE_POINTS, must_keep)

    curve = []
    for i in keep_idx:
        curve.append(
            {
                "q": _finite_or_none(quantiles[i]),
                "value": _finite_or_none(value[i]),
                "delta": _finite_or_none(delta[i]),
                "lower": _finite_or_none(lower_raw[i]),
                "upper": _finite_or_none(upper_raw[i]),
                "significant": bool(sig_mask[i]),
            }
        )
    # Final ascending-by-q guarantee (keep_idx is sorted, and quantiles is
    # already sorted ascending, so this is already true; re-sort defensively
    # in case of any future edit that breaks that invariant).
    curve.sort(key=lambda p: (p["q"] is None, p["q"]))

    significant_regions = [
        [_finite_or_none(a), _finite_or_none(b)] for a, b in result.significant_regions
    ]

    response = {
        "ok": True,
        "method": result.method,
        "alpha": _finite_or_none(result.alpha),
        "n": int(result.n),
        "m": int(result.m),
        "any_significant": bool(result.any_significant),
        "significant_regions": significant_regions,
        "mean_diff": _finite_or_none(result.mean_diff),
        "median_shift": _finite_or_none(result.median_shift),
        "welch_p": _finite_or_none(result.welch_p),
        "ks_p": _finite_or_none(result.ks_p),
        "summary": result.summary(),
        "curve": curve,
    }
    return sanitize_for_json(response)
