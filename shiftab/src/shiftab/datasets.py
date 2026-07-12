"""shiftab.datasets — synthetic A/B scenarios for demoing / exercising shiftab.

`make_ab(scenario, n, m, rng)` returns (control, treatment) numpy arrays.
Scenarios (see SPEC.md):
  "null"              - identical distributions.
  "location"          - pure location shift, +0.3 sigma.
  "scale"             - variance scaled x1.3, mean-matched.
  "tail_gain"         - lognormal base; top 15% of treatment scaled x1.5.
  "mean_neutral_tail" - top 10% of treatment inflated, rest deflated so
                        E[treatment] == E[control] *analytically* (uses the
                        true lognormal truncated-moment formula, not a
                        sample-mean correction).
  "revenue"           - zero-inflated lognormal, ~92%/91.5% zeros, slight
                        lognormal shift in the nonzero mass.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

__all__ = ["make_ab"]

_SCENARIOS = (
    "null",
    "location",
    "scale",
    "tail_gain",
    "mean_neutral_tail",
    "revenue",
)

# Shared lognormal base parameters (underlying-normal mu, sigma) used by the
# lognormal-based scenarios, chosen for a moderately realistic right skew.
_LN_MU = 0.0
_LN_SIGMA = 0.6


def _normalize_rng(rng) -> np.random.Generator:
    if isinstance(rng, np.random.Generator):
        return rng
    return np.random.default_rng(rng)


def _lognormal_partial_expectation(mu: float, sigma: float, t: float) -> float:
    """E[X ; X <= t] for X ~ Lognormal(mu, sigma^2) (unconditional partial
    expectation, i.e. integral of x*f(x) over (0, t]), via the standard
    closed-form reduction to a shifted normal CDF.
    """
    d = (np.log(t) - mu - sigma**2) / sigma
    return float(np.exp(mu + sigma**2 / 2.0) * stats.norm.cdf(d))


def make_ab(scenario: str, n: int, m: int, rng=None):
    """Generate a synthetic (control, treatment) pair for `scenario`.

    Parameters
    ----------
    scenario : one of the six canonical scenario names (see module docstring).
    n, m     : sample sizes for control / treatment.
    rng      : int seed, np.random.Generator, or None.
    """
    if scenario not in _SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; must be one of {_SCENARIOS}")
    if n < 1 or m < 1:
        raise ValueError("n and m must be positive")

    rng_ = _normalize_rng(rng)

    if scenario == "null":
        control = rng_.normal(0.0, 1.0, size=n)
        treatment = rng_.normal(0.0, 1.0, size=m)
        return control, treatment

    if scenario == "location":
        control = rng_.normal(0.0, 1.0, size=n)
        treatment = rng_.normal(0.3, 1.0, size=m)
        return control, treatment

    if scenario == "scale":
        control = rng_.normal(0.0, 1.0, size=n)
        treatment = rng_.normal(0.0, 1.3, size=m)
        return control, treatment

    if scenario == "tail_gain":
        control = rng_.lognormal(_LN_MU, _LN_SIGMA, size=n)
        treatment_raw = rng_.lognormal(_LN_MU, _LN_SIGMA, size=m)
        # analytic 85th-percentile threshold of the TRUE lognormal, not an
        # empirical quantile of the draws.
        t85 = float(np.exp(_LN_MU + _LN_SIGMA * stats.norm.ppf(0.85)))
        treatment = treatment_raw.copy()
        mask = treatment_raw >= t85
        treatment[mask] *= 1.5
        return control, treatment

    if scenario == "mean_neutral_tail":
        mu, sigma = _LN_MU, _LN_SIGMA
        p_tail = 0.10
        inflate = 1.5

        control = rng_.lognormal(mu, sigma, size=n)
        treatment_raw = rng_.lognormal(mu, sigma, size=m)

        # Analytic (population) threshold for the top decile.
        t = float(np.exp(mu + sigma * stats.norm.ppf(1.0 - p_tail)))
        mean_X = float(np.exp(mu + sigma**2 / 2.0))  # population mean
        partial = _lognormal_partial_expectation(mu, sigma, t)  # E[X; X<=t]
        F_t = 1.0 - p_tail  # by construction, = Phi((ln t - mu)/sigma)

        e_body = partial / F_t
        e_tail = (mean_X - partial) / p_tail

        # Solve deflate factor b analytically so that
        #   inflate * p_tail * e_tail + b * F_t * e_body == mean_X
        b = (mean_X - inflate * p_tail * e_tail) / (F_t * e_body)

        mask_tail = treatment_raw >= t
        treatment = np.where(mask_tail, treatment_raw * inflate, treatment_raw * b)
        return control, treatment

    if scenario == "revenue":
        mu, sigma = _LN_MU, 1.0
        p_nonzero_control = 0.08  # 92% zeros
        p_nonzero_treatment = 0.085  # 91.5% zeros
        shift = 0.05  # slight lognormal shift in log-mean

        control = np.zeros(n)
        nz_c = rng_.random(n) < p_nonzero_control
        control[nz_c] = rng_.lognormal(mu, sigma, size=int(nz_c.sum()))

        treatment = np.zeros(m)
        nz_t = rng_.random(m) < p_nonzero_treatment
        treatment[nz_t] = rng_.lognormal(mu + shift, sigma, size=int(nz_t.sum()))

        return control, treatment

    raise AssertionError("unreachable")  # scenario membership checked above
