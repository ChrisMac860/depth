"""shiftab — shift-function A/B analysis (Doksum & Sievers, 1976).

    from shiftab import shift_analysis, ShiftResult

See SPEC.md at the repo root for the full statistical / API contract.
"""

from .core import ShiftResult, shift_analysis

# Importing plot.py attaches ShiftResult.plot as a side effect.
from . import plot as _plot  # noqa: F401

__all__ = ["shift_analysis", "ShiftResult"]
