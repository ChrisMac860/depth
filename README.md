# DEPTH

**"See what the mean is hiding."**

DEPTH is a locally-hosted web app that runs shift-function A/B analysis (the
[Doksum & Sievers, 1976](https://en.wikipedia.org/wiki/Q%E2%80%93Q_plot)
shift function, via the validated `shiftab` engine) and renders an
*editable* shift-function chart — click any title, subtitle, or axis label
to retitle it in place — then exports the whole thing as a single
self-contained, downloadable HTML report. Three real-world example datasets
(small / medium / large) ship preloaded, and you can also paste or upload
your own two-column CSV.

A shift function answers a sharper question than "is the mean different?":
*where* in the distribution do the two groups differ, and by how much, with
a simultaneous confidence band across every quantile — not just at one
summary statistic.

## Design inspiration

The interface synthesizes three references (credited in the app footer and
in the exported report):

1. **[Greptile](https://greptile.com)** — off-white "paper" canvas with a
   faint crosshair grid texture, monospace numerals/stats, oversized bold
   display type, and angular/beveled buttons.
2. **[lapa.ninja](https://lapa.ninja) 2026 gallery** — a dark "depth" theme
   option: near-black canvas, electric-violet accent, rounded pill controls.
3. **2026 editorial trend (Huehaus / Webflow / Monolog)** — heavy blocky
   display typography in an asymmetric editorial layout with generous
   negative space.

## Install & run

```bash
pip install -r requirements.txt
python run.py
```

Then open the printed URL, **http://127.0.0.1:8000**, in a browser.
DEPTH binds to localhost only and makes no network calls at runtime; all
assets and datasets are local. (The hosted demo is the one exception: it
records a cookieless visit count via GoatCounter, which never includes
analysed data. Local runs load no counter.)

This repository vendors the `shiftab` statistics library under `shiftab/`
(engine source, contract, and licence attribution); `server/engine.py`
resolves it automatically. The library was validated separately against
pre-registered coverage, false-alarm, and power gates before this
application was built.

## Running the tests

```bash
python -m pytest tests/ -q
```

Tests that depend on the example datasets (`server/datasets/manifest.json`
and friends) skip gracefully if those files haven't been built yet
(`server/datasets/build_datasets.py`); the core `/api/analyze` contract
tests always run, using inline synthetic data.

## API

All responses are JSON. Errors are `HTTP 400` (or `404`/`500` for missing
resources) with `{"ok": false, "error": "<message>"}`. Success bodies
include `"ok": true`.

### `GET /`
Serves `server/static/index.html`.

### `GET /api/examples`
```json
{"ok": true, "examples": [ <manifest entry>, ... ]}
```
Returns the three example datasets (small, medium, large) in that order.

### `GET /api/examples/<id>`
`id` is one of `small`, `medium`, `large`.
```json
{"ok": true, "id": "small", "meta": <manifest entry>,
 "control": [ <numbers> ], "treatment": [ <numbers> ]}
```

### `POST /api/analyze`
Request:
```json
{"control": [...numbers...], "treatment": [...numbers...],
 "alpha": 0.05, "method": "ks_band", "n_boot": 2000, "quantile_grid": null}
```
`method` is `"ks_band"` (distribution-free simultaneous KS band, fast, the
default) or `"bootstrap"` (sup-t simultaneous band on a quantile grid).
Both arrays must be finite numbers, `n >= 10`, `m >= 10`, `0 < alpha <= 0.5`.

Response:
```json
{"ok": true,
 "method": "ks_band", "alpha": 0.05, "n": 176, "m": 68,
 "any_significant": true,
 "significant_regions": [[0.03, 0.87], [0.92, 1.0]],
 "mean_diff": 0.02, "median_shift": -0.17, "welch_p": 0.21, "ks_p": 1.5e-36,
 "summary": "<shiftab summary() text>",
 "curve": [ {"q": 0.01, "value": 3.2, "delta": -0.4,
             "lower": null, "upper": -0.1, "significant": true}, ... ]}
```

`curve` is downsampled to at most 400 points (evenly spaced along the
quantile axis, always keeping both endpoints and the point of maximum
`|delta|`), sorted ascending by `q`. Non-finite band edges (`±inf` from the
KS band, or any stray `NaN`) are serialized as JSON `null`, never as the
invalid JSON tokens `Infinity`/`NaN`.

Bootstrap runs are seeded with a fixed RNG constant (see `server/engine.py`)
so repeated calls with identical inputs are reproducible.
