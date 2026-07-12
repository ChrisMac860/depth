"""DEPTH Flask app — routes only. Statistics live in engine.py (shiftab
wrapper); datasets live in server/datasets/ (Agent C); frontend lives in
server/static/ (Agent B). See SPEC.md "API contract" for the frozen shapes
this module must produce byte-for-byte.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import engine

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATASETS_DIR = BASE_DIR / "datasets"

VALID_IDS = ("small", "medium", "large")
VALID_METHODS = ("ks_band", "bootstrap")

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")


def _error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


# ---------------------------------------------------------------------------
# GET / -> static/index.html   (GET /static/<path> is handled automatically
# by Flask's static route, configured above with static_url_path="/static")
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    if not (STATIC_DIR / "index.html").is_file():
        return _error(
            "server/static/index.html not found — the frontend has not been "
            "built yet.",
            500,
        )
    return send_from_directory(str(STATIC_DIR), "index.html")


# ---------------------------------------------------------------------------
# Dataset endpoints (files owned/written by Agent C; we only read them)
# ---------------------------------------------------------------------------


def _load_manifest() -> list:
    manifest_path = DATASETS_DIR / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.route("/api/examples")
def api_examples():
    try:
        manifest = _load_manifest()
    except FileNotFoundError:
        return _error(
            "server/datasets/manifest.json not found — datasets have not "
            "been built yet (run server/datasets/build_datasets.py).",
            500,
        )
    except (json.JSONDecodeError, OSError) as exc:
        return _error(f"failed to read manifest.json: {exc}", 500)
    return jsonify({"ok": True, "examples": manifest})


@app.route("/api/examples/<example_id>")
def api_example_detail(example_id: str):
    if example_id not in VALID_IDS:
        return _error(
            f"unknown example id {example_id!r}; expected one of {VALID_IDS}",
            404,
        )
    try:
        manifest = _load_manifest()
    except FileNotFoundError:
        return _error(
            "server/datasets/manifest.json not found — datasets have not "
            "been built yet (run server/datasets/build_datasets.py).",
            500,
        )
    except (json.JSONDecodeError, OSError) as exc:
        return _error(f"failed to read manifest.json: {exc}", 500)

    meta = next((entry for entry in manifest if entry.get("id") == example_id), None)
    if meta is None:
        return _error(f"no manifest entry for id {example_id!r}", 500)

    data_path = DATASETS_DIR / f"{example_id}.json"
    try:
        with data_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _error(f"server/datasets/{example_id}.json not found.", 500)
    except (json.JSONDecodeError, OSError) as exc:
        return _error(f"failed to read {example_id}.json: {exc}", 500)

    return jsonify(
        {
            "ok": True,
            "id": example_id,
            "meta": meta,
            "control": data.get("control", []),
            "treatment": data.get("treatment", []),
        }
    )


# ---------------------------------------------------------------------------
# POST /api/analyze
# ---------------------------------------------------------------------------


def _validate_numeric_array(value, name: str) -> list:
    if not isinstance(value, list) or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty array of numbers")
    out = []
    for i, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{name}[{i}] is not numeric")
        fv = float(v)
        if not math.isfinite(fv):
            raise ValueError(f"{name}[{i}] is not finite")
        out.append(fv)
    return out


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("request body must be a JSON object")

    try:
        control = _validate_numeric_array(body.get("control"), "control")
        treatment = _validate_numeric_array(body.get("treatment"), "treatment")
    except ValueError as exc:
        return _error(str(exc))

    if len(control) < 10:
        return _error(f"control sample size n={len(control)} < 10 (minimum required)")
    if len(treatment) < 10:
        return _error(f"treatment sample size m={len(treatment)} < 10 (minimum required)")

    alpha = body.get("alpha", 0.05)
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        return _error("alpha must be numeric")
    alpha = float(alpha)
    if not (0 < alpha <= 0.5):
        return _error(f"alpha must be in (0, 0.5], got {alpha}")

    method = body.get("method", "ks_band")
    if method not in VALID_METHODS:
        return _error(f"method must be one of {VALID_METHODS}, got {method!r}")

    n_boot = body.get("n_boot", 2000)
    if isinstance(n_boot, bool) or not isinstance(n_boot, (int, float)):
        return _error("n_boot must be an integer")
    n_boot = int(n_boot)
    if n_boot < 1:
        return _error("n_boot must be >= 1")

    quantile_grid = body.get("quantile_grid")
    if quantile_grid is not None:
        try:
            quantile_grid = _validate_numeric_array(quantile_grid, "quantile_grid")
        except ValueError as exc:
            return _error(str(exc))

    try:
        result = engine.analyze(
            control=control,
            treatment=treatment,
            alpha=alpha,
            method=method,
            n_boot=n_boot,
            quantile_grid=quantile_grid,
        )
    except ValueError as exc:
        return _error(str(exc))

    # Belt-and-suspenders: engine.analyze() already sanitizes, but re-run the
    # sweep on the whole payload so no Infinity/NaN can ever reach jsonify.
    return jsonify(engine.sanitize_for_json(result))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
