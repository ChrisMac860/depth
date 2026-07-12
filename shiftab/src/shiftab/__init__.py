"""shiftab — shift-function A/B analysis (Doksum & Sievers, 1976).

    from shiftab import shift_analysis, ShiftResult

See SPEC.md at the repo root for the full statistical / API contract.

Plotting is optional: importing plot.py attaches ShiftResult.plot, but it
requires matplotlib, which server deployments of DEPTH deliberately omit
(the web frontend renders its own SVG). Without matplotlib, ShiftResult.plot
stays None and everything else works unchanged.
"""

from .core import ShiftResult, shift_analysis

try:
    # Importing plot.py attaches ShiftResult.plot as a side effect.
    from . import plot as _plot  # noqa: F401
except ImportError:
    # matplotlib not installed — statistics fully functional, plotting off.
    pass

__all__ = ["shift_analysis", "ShiftResult"]
