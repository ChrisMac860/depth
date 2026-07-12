"""
DEPTH — build_datasets.py  (Agent C)

Fetches three REAL public CSVs at build time and writes:
  small.json, medium.json, large.json   -> {"control":[...], "treatment":[...]}
  manifest.json                          -> ordered [small, medium, large] entries
                                             matching the API contract in SPEC.md.

Re-runnable: overwrites all four files each time. Values are kept RAW
(not normalized). Every emitted number is finite (non-finite / NA rows
are dropped before writing).

Run:  python build_datasets.py   (from this directory, or anywhere — paths
      are resolved relative to this file).
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

TIPS_URL = "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/tips.csv"
TAXIS_URL = "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/taxis.csv"
DIAMONDS_URL = "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/diamonds.csv"

USER_AGENT = "depth-dataset-builder/1.0 (+local build script)"


def fetch_csv(url: str, timeout: int = 30) -> list[dict]:
    """Download a CSV over HTTP(S) and parse it into a list of dict rows.

    Raises a clear RuntimeError on any HTTP/network failure so the caller
    can decide whether to fall back to an alternate source.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"network error fetching {url}: {e.reason}") from e
    except Exception as e:  # noqa: BLE001 - want a clear message for any failure
        raise RuntimeError(f"unexpected error fetching {url}: {e}") from e

    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        raise RuntimeError(f"fetched {url} but parsed zero rows")
    return rows


def to_finite_floats(values) -> list[float]:
    """Coerce an iterable of raw cell values to a list of finite floats,
    silently dropping anything blank/non-numeric/NaN/inf."""
    out = []
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s == "" or s.lower() in ("nan", "na", "n/a", "null", "none"):
            continue
        try:
            f = float(s)
        except ValueError:
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def write_group_json(path: Path, control: list[float], treatment: list[float]) -> None:
    payload = {"control": control, "treatment": treatment}
    # Compact but not minified-to-illegibility; numbers stay numbers (not strings).
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


# ---------------------------------------------------------------------------
# SMALL — tips.csv: tip (USD), control = Dinner, treatment = Lunch
# ---------------------------------------------------------------------------

def build_small() -> dict:
    rows = fetch_csv(TIPS_URL)
    control = to_finite_floats(r["tip"] for r in rows if r.get("time") == "Dinner")
    treatment = to_finite_floats(r["tip"] for r in rows if r.get("time") == "Lunch")

    write_group_json(HERE / "small.json", control, treatment)

    n, m = len(control), len(treatment)
    print(f"[small] tips.csv -> tip (USD), Dinner(n={n}) vs Lunch(m={m})")

    return {
        "id": "small",
        "name": "Restaurant tips",
        "size_label": "small",
        "n": n,
        "m": m,
        "description": (
            "Tip amounts left by restaurant parties, split by meal service "
            "(Dinner vs Lunch), from the classic Seaborn 'tips' dataset."
        ),
        "provenance": (
            "Real data: seaborn-data/tips.csv "
            f"({TIPS_URL}). Variable: tip (USD). Split on `time`: "
            "control = Dinner rows, treatment = Lunch rows. No filtering "
            "beyond dropping non-numeric/blank tip values (none were dropped "
            "in practice; the source file is clean)."
        ),
        "unit": "USD",
        "control_label": "Dinner",
        "treatment_label": "Lunch",
        "suggested_title": "Tip amount: Dinner vs Lunch",
        "default_method": "ks_band",
    }


# ---------------------------------------------------------------------------
# MEDIUM — taxis.csv: control vs treatment = payment credit card vs cash
# ---------------------------------------------------------------------------

def build_medium() -> dict:
    rows = fetch_csv(TAXIS_URL)

    # Decision (documented honestly in provenance): use `fare`, not `tip`.
    # In this dataset cash tips are not electronically recorded and are
    # therefore ALWAYS 0.00 for payment == 'cash' (a data-collection
    # artifact of NYC taxi meters, not a real behavioral effect) — using
    # `tip` here would compare a real distribution against a degenerate
    # spike at zero, which is not a genuine "shape difference" example.
    # `fare` is populated and right-skewed for both groups, so we use it.
    clean = [r for r in rows if r.get("payment") in ("credit card", "cash")]

    control = to_finite_floats(r["fare"] for r in clean if r["payment"] == "credit card")
    treatment = to_finite_floats(r["fare"] for r in clean if r["payment"] == "cash")

    write_group_json(HERE / "medium.json", control, treatment)

    n, m = len(control), len(treatment)
    print(f"[medium] taxis.csv -> fare (USD), credit card(n={n}) vs cash(m={m})")

    dropped_null_payment = len(rows) - len(clean)

    return {
        "id": "medium",
        "name": "NYC taxi fares",
        "size_label": "medium",
        "n": n,
        "m": m,
        "description": (
            "NYC taxi ride fares, split by payment method (credit card vs "
            "cash), from the Seaborn 'taxis' dataset."
        ),
        "provenance": (
            "Real data: seaborn-data/taxis.csv "
            f"({TAXIS_URL}). Variable: fare (USD), not tip. Cash tips in "
            "this dataset are never electronically recorded and are always "
            "0.00, which would make a tip comparison degenerate rather than "
            "a genuine shape difference, so fare was used instead. Split on "
            "`payment`: control = 'credit card' rows, treatment = 'cash' "
            f"rows. Dropped {dropped_null_payment} rows with null/other "
            "payment value out of "
            f"{len(rows)} total. Zero fares were not present; none dropped "
            "for that reason."
        ),
        "unit": "USD",
        "control_label": "Credit card",
        "treatment_label": "Cash",
        "suggested_title": "Taxi fare: Credit card vs Cash",
        "default_method": "ks_band",
    }


# ---------------------------------------------------------------------------
# LARGE — diamonds.csv: price (USD), control = Ideal, treatment = Premium
# ---------------------------------------------------------------------------

def build_large() -> dict:
    rows = fetch_csv(DIAMONDS_URL)
    control = to_finite_floats(r["price"] for r in rows if r.get("cut") == "Ideal")
    treatment = to_finite_floats(r["price"] for r in rows if r.get("cut") == "Premium")

    write_group_json(HERE / "large.json", control, treatment)

    n, m = len(control), len(treatment)
    print(f"[large] diamonds.csv -> price (USD), Ideal(n={n}) vs Premium(m={m})")

    return {
        "id": "large",
        "name": "Diamond prices",
        "size_label": "large",
        "n": n,
        "m": m,
        "description": (
            "Diamond sale prices, split by cut quality (Ideal vs Premium), "
            "from the classic Seaborn 'diamonds' dataset."
        ),
        "provenance": (
            "Real data: seaborn-data/diamonds.csv "
            f"({DIAMONDS_URL}). Variable: price (USD). Split on `cut`: "
            "control = Ideal rows, treatment = Premium rows. No filtering "
            "beyond dropping non-numeric/blank price values (none were "
            "dropped in practice; the source file is clean)."
        ),
        "unit": "USD",
        "control_label": "Ideal",
        "treatment_label": "Premium",
        "suggested_title": "Diamond price: Ideal vs Premium cut",
        "default_method": "ks_band",
    }


BUILDERS = [
    ("small", build_small),
    ("medium", build_medium),
    ("large", build_large),
]


def main() -> int:
    manifest = []
    failures = []

    for key, builder in BUILDERS:
        try:
            entry = builder()
        except Exception as e:  # noqa: BLE001
            print(f"[{key}] FAILED: {e}", file=sys.stderr)
            failures.append((key, str(e)))
            continue
        manifest.append(entry)

    if failures:
        print(
            "\nERROR: one or more datasets failed to build and had no "
            "fallback applied:",
            file=sys.stderr,
        )
        for key, err in failures:
            print(f"  - {key}: {err}", file=sys.stderr)
        print(
            "No real alternate source or synthetic fallback is wired up in "
            "this build — fix connectivity/URL and re-run.",
            file=sys.stderr,
        )
        return 1

    (HERE / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print("\nmanifest.json written. Summary:")
    for entry in manifest:
        print(
            f"  {entry['id']:7s} n={entry['n']:>6d}  m={entry['m']:>6d}  "
            f"total={entry['n'] + entry['m']:>6d}  ({entry['size_label']})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
