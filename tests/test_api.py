"""Backend contract tests for DEPTH (SPEC.md "API contract" + "G1 BACKEND
CONTRACT" gate). Run with:

    python -m pytest tests/ -q

from the depth/ repo root.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from server.app import app, DATASETS_DIR

MANIFEST_PATH = DATASETS_DIR / "manifest.json"
EXAMPLE_IDS = ("small", "medium", "large")


def _strict_json_loads(raw: bytes | str):
    """json.loads that raises ValueError on the invalid-JSON tokens
    Infinity/-Infinity/NaN, instead of silently accepting them the way the
    stdlib does by default. Used to prove no non-finite float leaked through.
    """

    def _reject(token):
        raise ValueError(f"non-finite token leaked into JSON output: {token}")

    return json.loads(raw, parse_constant=_reject)


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _make_normal(n, m, seed=0, shift=0.0, scale=1.0):
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n).tolist()
    y = (rng.standard_normal(m) * scale + shift).tolist()
    return x, y


# ---------------------------------------------------------------------------
# /api/examples, /api/examples/<id> — skip gracefully if datasets aren't
# built yet (they're owned by a different agent).
# ---------------------------------------------------------------------------

manifest_missing = pytest.mark.skipif(
    not MANIFEST_PATH.is_file(),
    reason="server/datasets/manifest.json not built yet (Agent C's output)",
)


@manifest_missing
def test_examples_returns_three_entries(client):
    resp = client.get("/api/examples")
    assert resp.status_code == 200
    body = _strict_json_loads(resp.data)
    assert body["ok"] is True
    assert len(body["examples"]) == 3
    ids = [e["id"] for e in body["examples"]]
    assert ids == list(EXAMPLE_IDS)
    required_fields = {
        "id",
        "name",
        "size_label",
        "n",
        "m",
        "description",
        "provenance",
        "unit",
        "control_label",
        "treatment_label",
        "suggested_title",
        "default_method",
    }
    for entry in body["examples"]:
        assert required_fields <= set(entry.keys())


@manifest_missing
@pytest.mark.parametrize("example_id", EXAMPLE_IDS)
def test_example_detail_returns_arrays_matching_manifest(client, example_id):
    resp = client.get(f"/api/examples/{example_id}")
    assert resp.status_code == 200
    body = _strict_json_loads(resp.data)
    assert body["ok"] is True
    assert body["id"] == example_id
    assert isinstance(body["control"], list) and len(body["control"]) > 0
    assert isinstance(body["treatment"], list) and len(body["treatment"]) > 0
    assert len(body["control"]) == body["meta"]["n"]
    assert len(body["treatment"]) == body["meta"]["m"]
    assert all(isinstance(v, (int, float)) for v in body["control"])
    assert all(isinstance(v, (int, float)) for v in body["treatment"])


def test_example_detail_unknown_id_404(client):
    resp = client.get("/api/examples/huge")
    assert resp.status_code == 404
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False


# ---------------------------------------------------------------------------
# /api/analyze — happy path, always run (inline synthetic data, no dataset
# dependency).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["ks_band", "bootstrap"])
def test_analyze_happy_path(client, method):
    x, y = _make_normal(200, 150, seed=1, shift=0.5)
    resp = client.post(
        "/api/analyze",
        json={"control": x, "treatment": y, "alpha": 0.05, "method": method, "n_boot": 500},
    )
    assert resp.status_code == 200
    body = _strict_json_loads(resp.data)  # raises if Infinity/NaN leaked

    assert body["ok"] is True
    assert body["method"] == method
    assert body["n"] == 200
    assert body["m"] == 150
    assert isinstance(body["any_significant"], bool)
    assert isinstance(body["significant_regions"], list)
    assert isinstance(body["summary"], str) and body["summary"]

    for key in ("mean_diff", "median_shift", "welch_p", "ks_p"):
        assert body[key] is None or isinstance(body[key], (int, float))

    curve = body["curve"]
    assert isinstance(curve, list) and len(curve) > 0
    assert len(curve) <= 400

    qs = [p["q"] for p in curve]
    assert qs == sorted(qs), "curve must be sorted ascending by q"

    for point in curve:
        assert set(point.keys()) == {"q", "value", "delta", "lower", "upper", "significant"}
        assert isinstance(point["significant"], bool)
        assert point["lower"] is None or isinstance(point["lower"], (int, float))
        assert point["upper"] is None or isinstance(point["upper"], (int, float))
        assert isinstance(point["delta"], (int, float))


def test_analyze_downsamples_large_curve_to_400(client):
    # ks_band's grid is one point per control observation -> n=20000 forces
    # the downsample path.
    x, y = _make_normal(20000, 5000, seed=2, shift=1.0, scale=1.5)
    resp = client.post(
        "/api/analyze",
        json={"control": x, "treatment": y, "alpha": 0.05, "method": "ks_band"},
    )
    assert resp.status_code == 200
    body = _strict_json_loads(resp.data)
    curve = body["curve"]
    assert len(curve) <= 400
    qs = [p["q"] for p in curve]
    assert qs == sorted(qs)
    # endpoints kept
    assert curve[0]["q"] == pytest.approx(min(qs))
    assert curve[-1]["q"] == pytest.approx(max(qs))


def test_analyze_ks_band_produces_null_band_edges_at_extremes(client):
    # SPEC: "±inf band edges from ks_band are NOT valid JSON. Convert every
    # non-finite lower/upper to null." A small n=m=15 normal sample reliably
    # produces +/-inf at the extreme quantiles for the KS band.
    x, y = _make_normal(15, 15, seed=3)
    resp = client.post(
        "/api/analyze",
        json={"control": x, "treatment": y, "alpha": 0.05, "method": "ks_band"},
    )
    assert resp.status_code == 200
    # Round-trip through a strict parser: if Infinity/-Infinity/NaN literals
    # leaked into the raw response text, this raises ValueError.
    body = _strict_json_loads(resp.data)
    assert body["ok"] is True
    curve = body["curve"]
    nulls = [p for p in curve if p["lower"] is None or p["upper"] is None]
    assert len(nulls) > 0, "expected at least one unbounded band edge at n=m=15"
    # Also verify at the raw-bytes level that the invalid JSON tokens never
    # appear in the payload (defense in depth beyond parse_constant).
    raw_text = resp.data.decode("utf-8")
    assert "Infinity" not in raw_text
    assert "NaN" not in raw_text


def test_analyze_significant_regions_present_and_shaped(client):
    x, y = _make_normal(300, 300, seed=4, shift=3.0)  # large, obvious shift
    resp = client.post(
        "/api/analyze",
        json={"control": x, "treatment": y, "alpha": 0.05, "method": "ks_band"},
    )
    body = _strict_json_loads(resp.data)
    assert body["any_significant"] is True
    assert len(body["significant_regions"]) >= 1
    for region in body["significant_regions"]:
        assert len(region) == 2
        a, b = region
        assert isinstance(a, (int, float)) and isinstance(b, (int, float))
        assert a <= b


# ---------------------------------------------------------------------------
# /api/analyze — validation (400s)
# ---------------------------------------------------------------------------


def test_analyze_rejects_n_below_minimum(client):
    x = list(range(9))  # n=9 < 10
    y = list(range(20))
    resp = client.post("/api/analyze", json={"control": x, "treatment": y})
    assert resp.status_code == 400
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False
    assert "error" in body


def test_analyze_rejects_m_below_minimum(client):
    x = list(range(20))
    y = list(range(5))  # m=5 < 10
    resp = client.post("/api/analyze", json={"control": x, "treatment": y})
    assert resp.status_code == 400
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False


@pytest.mark.parametrize("bad_alpha", [0, -0.1, 0.6, 1.0, "not-a-number", None])
def test_analyze_rejects_bad_alpha(client, bad_alpha):
    x, y = _make_normal(20, 20)
    resp = client.post(
        "/api/analyze",
        json={"control": x, "treatment": y, "alpha": bad_alpha},
    )
    assert resp.status_code == 400
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False


def test_analyze_rejects_non_numeric_control(client):
    x = ["a", "b", "c"] + list(range(20))
    y = list(range(20))
    resp = client.post("/api/analyze", json={"control": x, "treatment": y})
    assert resp.status_code == 400
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False


def test_analyze_rejects_non_finite_values(client):
    x = [float("inf")] + list(range(20))
    y = list(range(20))
    resp = client.post("/api/analyze", json={"control": x, "treatment": y})
    assert resp.status_code == 400
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False


def test_analyze_rejects_bad_method(client):
    x, y = _make_normal(20, 20)
    resp = client.post(
        "/api/analyze",
        json={"control": x, "treatment": y, "method": "not_a_method"},
    )
    assert resp.status_code == 400
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False


def test_analyze_rejects_missing_body(client):
    resp = client.post("/api/analyze", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False


def test_analyze_rejects_empty_arrays(client):
    resp = client.post("/api/analyze", json={"control": [], "treatment": []})
    assert resp.status_code == 400
    body = _strict_json_loads(resp.data)
    assert body["ok"] is False
