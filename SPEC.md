# DEPTH — SPEC (architect: Claude Fable; builders: subagents)

**DEPTH** is a locally-hosted web app that runs shift-function A/B analysis (the
validated `shiftab` engine) and renders an *editable* shift-function chart the user
can retitle/relabel by clicking, then export as a single self-contained, downloadable
HTML report. Three real-world example datasets (small / medium / large) ship preloaded.

Tagline: **"See what the mean is hiding."**

This spec is FROZEN. Three agents build in disjoint directories against the contracts
below. Do not change contract shapes; if something is underspecified, choose the
simplest option consistent with the gates and note it in your report.

## Directory layout (STRICT — agent ownership in brackets)

```
depth/
  SPEC.md                        (architect — read-only for agents)
  run.py                         [A]  launcher: python run.py -> serves on http://127.0.0.1:8000
  requirements.txt               [A]
  README.md                      [A]
  server/
    app.py                       [A]  Flask app + routes
    engine.py                    [A]  shiftab wrapper: path resolve, inf->None, curve downsample
    __init__.py                  [A]
    datasets/
      build_datasets.py          [C]  fetches real CSVs, writes the three files below
      small.json                 [C]
      medium.json                [C]
      large.json                 [C]
      manifest.json              [C]  list of {id,name,size_label,n,m,description,provenance,unit,control_label,treatment_label,suggested_title,default_method}
    static/
      index.html                 [B]
      styles.css                 [B]
      app.js                     [B]
      (any fonts/assets)         [B]  self-hosted only, no external CDNs
  tests/
    test_api.py                  [A]  backend contract tests (pytest)
```

Agent A owns `server/app.py, server/engine.py, server/__init__.py, run.py,
requirements.txt, README.md, tests/test_api.py`. Agent B owns `server/static/*`.
Agent C owns `server/datasets/*`. NO cross-writes.

Python >=3.12. Backend deps: flask, numpy, scipy (shiftab's deps). Frontend: vanilla
HTML/CSS/JS, NO external network calls at runtime (self-contained, offline-capable).

## shiftab reuse (Agent A)

`shiftab` lives at repo-root sibling `../shiftab/src/shiftab`. In `engine.py`, resolve
its path robustly and `sys.path.insert` it (do NOT copy the library):
```python
SHIFTAB_SRC = (Path(__file__).resolve().parents[2] / "shiftab" / "src")
```
(parents[2]から depth/server/engine.py -> repo root). Verify the import works; if the
layout differs, search upward for a `shiftab/src` dir. Call
`shiftab.shift_analysis(control, treatment, alpha, method, n_boot, rng)`.

## API contract (Agent A serves; Agent B consumes EXACTLY this)

All JSON. Errors: HTTP 400 + `{"ok": false, "error": "<message>"}`. Success bodies
include `"ok": true`.

### `GET /`  -> serves `static/index.html`.  `GET /static/<path>` -> assets.

### `GET /api/examples`
```json
{"ok": true, "examples": [ <manifest entry>, <manifest entry>, <manifest entry> ]}
```
Each manifest entry (from Agent C's manifest.json), ordered small, medium, large:
```json
{"id":"small","name":"Restaurant tips","size_label":"small","n":176,"m":68,
 "description":"...","provenance":"...","unit":"USD",
 "control_label":"Dinner","treatment_label":"Lunch",
 "suggested_title":"Tip amount: Dinner vs Lunch","default_method":"ks_band"}
```

### `GET /api/examples/<id>`   (id in {small, medium, large})
```json
{"ok": true, "id":"small", "meta": <manifest entry>,
 "control": [ <numbers> ], "treatment": [ <numbers> ]}
```

### `POST /api/analyze`
Request:
```json
{"control":[...nums...], "treatment":[...nums...],
 "alpha":0.05, "method":"ks_band", "n_boot":2000, "quantile_grid":null}
```
`method` in {"ks_band","bootstrap"}. Validate: arrays of finite numbers, n>=10, m>=10,
0<alpha<=0.5. On invalid input return 400 + error (mirror shiftab's ValueErrors).

Response:
```json
{"ok": true,
 "method":"ks_band", "alpha":0.05, "n":176, "m":68,
 "any_significant": true,
 "significant_regions": [[0.03,0.87],[0.92,1.0]],
 "mean_diff": 0.02, "median_shift": -0.17, "welch_p": 0.21, "ks_p": 1.5e-36,
 "summary": "<shiftab summary() text>",
 "curve": [ {"q":0.01,"value":<control value at q>,"delta":<num>,
             "lower":<num|null>,"upper":<num|null>,"significant":<bool>}, ... ]}
```

CRITICAL serialization rules (Agent A):
- `±inf` band edges from ks_band are NOT valid JSON. Convert every non-finite
  lower/upper to `null`. Frontend treats null as "unbounded at this quantile."
- `NaN` anywhere -> `null`.
- **Downsample `curve` to <= 400 points** evenly spaced along the quantile axis
  (the large example has ~20k grid points; sending all of them bloats the DOM).
  Keep the point of maximum |delta| and both endpoints. `value` is the control-side
  value at that quantile (for the secondary "approx. value" axis); for bootstrap use
  the empirical control quantile.
- `significant` per point = band excludes 0 (lower>0 or upper<0), computed BEFORE
  downsampling from the full arrays, then carried onto the kept points.
- `significant_regions` are contiguous quantile intervals (from shiftab), passed through.

`curve` MUST be sorted ascending by `q`.

## Design language (Agent B) — synthesize the THREE references, don't copy one

Provenance (required: the README/UI must credit these three as inspiration):
1. **Greptile (greptile.com)** — off-white "paper" canvas with a faint crosshair/`+`
   grid texture; a single vivid accent; MONOSPACE for all numerals/stats/axis ticks
   and a slim top status ticker; oversized ultra-bold near-black display type;
   angular/beveled corners (clip-path) on primary buttons.
2. **lapa.ninja 2026 gallery** — a dark "depth" theme option: deep near-black canvas,
   electric-violet accent, rounded pill secondary controls.
3. **2026 editorial trend (Huehaus / Webflow / Monolog)** — heavy blocky display
   typography, ASYMMETRIC editorial layout (not a centered symmetric hero), generous
   negative space, one warm secondary tone.

Concrete requirements:
- Product name **DEPTH** as an oversized display wordmark. Tagline present.
- **Two themes**: "Paper" (light, default) and "Depth" (dark), toggle in the header;
  persist choice in localStorage; crossfade on switch. Both must be legible (WCAG AA
  body text).
- Type: a bold grotesque/display face for headings (self-hosted or system stack like
  `"Inter", "Helvetica Neue", Arial` at heavy weights) + a monospace stack
  (`"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace`) for numbers/ticks.
  No Google Fonts network calls — use system stacks or self-host.
- Accent tokens as CSS variables: `--ink` (near-black), `--accent` (electric violet
  ~#6C4CF1 in Paper / brighter in Depth), `--signal` (warm amber/red ~#F0603A for
  significant regions), `--paper`, `--grid`. All colors via variables so theming is
  one place.
- Layout regions: header (wordmark + tagline + theme toggle), a left/entry column
  (example picker with 3 cards small/medium/large + a "paste/upload CSV" affordance +
  method toggle ks_band/bootstrap + alpha), and a main results panel (the editable
  chart + a stat readout + the plain-language "what the mean hides" callout + a
  Download button).
- **Animations** (respect `prefers-reduced-motion: reduce` -> disable/instant):
  - staggered fade/slide-in of header + panels on first load;
  - the shift **curve draws left-to-right** (stroke-dashoffset) and the confidence
    **band fades+expands** in when results arrive;
  - stat numbers **count up** to their value;
  - significant-region shading **sweeps in**;
  - button hover/press micro-interactions; theme crossfade.

## The chart (Agent B) — inline SVG, editable, exportable

Render the `curve` as an inline `<svg>` you build in JS (NO charting library — this
keeps it offline and keeps text nodes directly editable):
- X axis = control quantile (0..1). Y axis = shift Δ (treatment − control).
- Shaded simultaneous confidence band between `lower`/`upper`; where a bound is `null`
  (unbounded), clamp the band to the plot edge (do not drop the segment).
- Δ line on top; dashed zero line; significant regions highlighted with `--signal`.
- Secondary top axis annotating approximate control **value** at ticks (from `curve[].value`).
- Stat tiles (monospace): n, m, mean_diff, median_shift, welch_p, ks_p, and a verdict
  chip ("Shift detected" / "No shift detected").

**Editable text (the headline feature).** These SVG text elements are click-to-edit:
`chart title`, `chart subtitle`, `x-axis label`, `y-axis label`. Interaction:
click the text -> it becomes an editable field in place (contenteditable or an
overlaid `<input>` positioned over the text) -> Enter or blur commits -> the SVG
`<text>` updates. Escape cancels. A subtle affordance (dotted underline on hover +
a tiny pencil) signals editability. Edited strings are the single source of truth and
MUST flow into the export. Seed defaults from the example's `suggested_title` /
`control_label` / `treatment_label` / `unit`.

**Export (Download report).** A button builds ONE self-contained `.html` string and
triggers a client-side download (Blob + `<a download>`), filename like
`depth-report-<id-or-custom>-<yyyymmdd>.html`. The exported file:
- is fully standalone: inline CSS, the CURRENT edited SVG (with the user's titles/
  labels baked in), no external requests, opens offline in any browser;
- contains: the DEPTH wordmark + tagline, the chart SVG, a clean stats table
  (n, m, method, alpha, mean_diff, median_shift, welch_p, ks_p, verdict), the
  significant-region list, the plain-language callout, the dataset provenance line,
  and a generated-on timestamp;
- is "simple and clean" — a single readable column, print-friendly, no app chrome.
- Provide a JS function `buildReportHTML(state) -> string` so QA can unit-check it.

Client-side CSV parsing for the upload/paste path: parse two numeric columns OR two
newline groups; on parse failure show a friendly inline error. (Analysis still goes
through `POST /api/analyze`.)

## Datasets (Agent C) — REAL-WORLD, three sizes, differing SHAPE

Fetch real public CSVs at BUILD time (you have WebFetch/curl). Preferred sources
(reliable raw GitHub, famous datasets — right-skewed with genuine shape differences so
the shift function is non-trivial, not just a location shift):

- **SMALL** — `tips.csv`
  `https://raw.githubusercontent.com/mwaskom/seaborn-data/master/tips.csv`
  Variable: `tip` (USD). control = Dinner tips, treatment = Lunch tips
  (split on `time`). ~n176 / m68.
- **MEDIUM** — `taxis.csv`
  `https://raw.githubusercontent.com/mwaskom/seaborn-data/master/taxis.csv`
  Variable: `tip` or `fare` (USD). control vs treatment = `payment` credit_card vs
  cash (drop rows with null payment; you may drop zero tips or keep them — document
  the choice). ~thousands per group.
- **LARGE** — `diamonds.csv`
  `https://raw.githubusercontent.com/mwaskom/seaborn-data/master/diamonds.csv`
  Variable: `price` (USD). control = Ideal cut, treatment = Premium cut. ~21k / ~14k.

Write each as `{"control":[...nums...], "treatment":[...nums...]}` in
`small.json` / `medium.json` / `large.json`, plus `manifest.json` (array of the entry
shape above, ordered small, medium, large). Each entry's `provenance` must name the
real source and any filtering you did — be HONEST. If a fetch fails, fall back to
another real source or clearly label a grounded synthetic and say so in `provenance`;
never present synthetic as real.

`build_datasets.py` must be re-runnable and must print the resulting n/m per set. Keep
raw values as-is (do not normalize). Ensure all values finite; drop non-finite/NA rows.

## PRE-REGISTERED PASS/FAIL GATES (QA runs these; verdict is binary)

G1 BACKEND CONTRACT: `pytest tests/` passes. `/api/examples` returns 3 entries
   (small/medium/large) with all manifest fields. `/api/examples/<id>` returns arrays
   of the stated n/m. `/api/analyze` on each example returns `ok:true`, a `curve` with
   <=400 points sorted by q, no `Infinity`/`NaN` in the JSON (null instead), and
   `significant`/`significant_regions` present.

G2 ENGINE FIDELITY: for a fixed input, DEPTH's `/api/analyze` numbers
   (mean_diff, median_shift, welch_p, ks_p, any_significant, significant_regions)
   MATCH calling `shiftab.shift_analysis` directly (within 1e-9 for floats; identical
   booleans/regions). The web layer must not alter the statistics.

G3 REAL DATA + PRODUCT CLAIM: all three example datasets load and analyze without
   error; at least the medium and large (right-skewed, real) produce a non-trivial
   shift (any_significant true with >=1 significant region). Provenance strings name a
   real source. Sizes are genuinely small/medium/large (roughly: small <300 total,
   medium 1k–15k, large >30k total).

G4 EDITABLE + EXPORT: driven in a REAL browser (architect QA): loading an example
   renders the chart; editing the chart title AND an axis label by click-then-type
   changes the on-screen SVG text; clicking Download produces a standalone `.html`
   whose contents include the EDITED title/label text and the stats table, and which
   opens with no network (no external URLs / no `http` asset refs in the file).

G5 FRONTEND INTEGRITY & DESIGN: app loads with zero console errors; no external
   network requests at runtime (all assets local); both themes render legibly and the
   toggle works; `prefers-reduced-motion` disables animation; the three inspiration
   sources are credited. Reasonable responsiveness (usable at 1280px; no layout
   overflow that hides controls).

VERDICT = PASS iff G1–G5 all pass after at most one debugging iteration (a fix must not
weaken any gate). Otherwise FAIL with a written diagnosis.

## Notes for builders
- Bind the server to `127.0.0.1:8000` (localhost only — it's a local product).
- Keep everything reproducible and offline at runtime. Build-time fetches (datasets)
  are fine; runtime must need no network.
- Do not install new packages beyond flask (numpy/scipy already present). If flask
  needs installing, note it; the launcher/README must state `pip install -r requirements.txt`.
- Handle the large dataset's performance: ks_band is the default and is fast; if
  bootstrap is selected on the large set, it's acceptable to be slower but must not error.
