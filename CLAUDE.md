# CLAUDE.md

Context for Claude Code working in this repo.

## What this is

A small data-analysis pipeline for OMRON Complete blood-pressure CSV
exports (Spanish locale: `Fecha`, `Hora`, `Sistólica`, `Diastólica`,
`Pulso`, …). The output is a multi-page PDF (or Markdown) report plus
intermediate CSVs and PNG charts.

Cardiology-oriented additions on the PDF:

* a **clinical-summary cover page** with day/night means, nocturnal
  dip %, morning surge, ACC/AHA stage distribution, and ESH home-BP
  time-in-range numbers — i.e. the headlines a clinician will scan
  first;
* a **time-in-range page** showing the overall ACC/AHA distribution
  plus a per-day stacked-bar of the same stages over the reporting
  window;
* a **weekly clinical digest** table that reproduces the cover-page
  headlines (mean BP, Δ vs prior week, dip %, morning surge,
  ESH-above %, Stage-2 days) for every ISO week present in the data,
  flagging dip/surge cells where night coverage is empty or sparse
  (`n_n<5`);
* a **weekly mini-report page** rendered per ISO week, showing that
  week's clinical metrics, variance (SD / CV / range), dipper /
  surge / ESH / Stage-2 patterns, Δ-vs-prior-week with up/down arrows,
  three per-day trend panels for sys / dia / pulse, and a
  time-in-range bar for the week. Drawn at PDF-render time from `df`
  filtered to each week, plus `weekly_clinical_summary.csv` for the
  precomputed metrics;
* a **diurnal-pattern page** that surfaces the morning-surge proxy
  (`peak 06–10h − trough 00–06h`) as a single number.

## Code layout

- `bp_utils.py` — shared helpers. `load_omron_csv(path)` is the entry
  point: it reads the CSV, locates the date / time / sys / dia / pulse
  columns by semantic kind (so headers in Spanish / English / French /
  German / Italian / Portuguese / Dutch all work), parses the
  date values via `parse_dt()`, and returns a tidy DataFrame with the
  standard column names `ts`, `sys`, `dia`, `pulse`. Imported by both
  `analyze.py` and `_render_pdf.py`.
- `normalize_csv.py` — tiny CLI wrapper around `load_omron_csv` that
  writes its tidy DataFrame as `ts,sys,dia,pulse`. Used by
  `omron_merge.sh` to put heterogeneous inputs into a common shape
  before csvstacking.
- `analyze.py` — single pandas script that computes daily / period /
  weekly statistics, writes the per-stat CSVs, and renders every PNG
  via matplotlib. Single source of truth for the data plumbing.
- `_render_pdf.py` — matplotlib `PdfPages` composer. Reads the CSVs
  + PNGs produced by `analyze.py` and assembles `report.pdf`. Treats
  the **current working directory** as its data root
  (`HERE = Path.cwd()`), not the script's own location.
- `make_report.sh` — orchestrator. Default builds the PDF; `--md`
  builds the Markdown variant by awk-templating the CSVs. Honors two
  env vars so the container can override without code changes:
  - `WORK_DIR` (where input/output live; default = script dir)
  - `PYTHON_BIN` (interpreter; default = `./env/bin/python`)
- `bp-report` — host-side launcher around `podman run`. Takes a CSV
  path and optional `-o OUTPUT_DIR`, mounts things correctly.
- `entrypoint.sh` — container entrypoint. Accepts optional positional
  CSV path + `--pdf`/`--md`. Validates args before running analysis.
- `Containerfile` — `python:3.13-slim` + pip deps. No conda inside.
- `.github/workflows/build-image.yml` — buildah/podman GitHub Action
  that publishes to `ghcr.io/wildcommitter/omron-bp-report-generator`.

## Running things

```
./env/bin/python analyze.py        # regenerate stats + PNGs
./make_report.sh                   # build report.pdf
./make_report.sh --md              # build report.md instead
./bp-report path/to/file.csv       # run via container
podman build -t bp-report .        # rebuild container image
```

## Conventions to preserve

- **Python interpreter** is the project-local conda env at `./env/`
  (created with `~/anaconda3/bin/conda`). System Python has none of
  the needed deps — always use `./env/bin/python`.
- **input.csv is personal health data** and is gitignored. Don't add
  it back to the repo, don't commit it via `git add -A`.
- **Chart y-axis ranges** are derived from the data via an
  `autoscale()` helper in `analyze.py` — don't hardcode ranges. Only
  clinical thresholds (120/130/140 mmHg sys, 80/90 dia, 100 bpm) are
  hardcoded constants.
- **8-hour period boundaries** start at 07:00 and are defined by the
  `period()` function in `analyze.py`. Change there to shift them.
- **Locale-tolerant CSV ingest** lives in `bp_utils.load_omron_csv()`,
  which accepts two input shapes:
    * the **OMRON Complete app export** — separate `Fecha`/`Hora`
      columns in the device's locale (Spanish / English / French /
      German / Italian / Portuguese / Dutch month abbreviations + ISO
      8601 + numeric formats), pulse column `Pulso (ppm)` etc.;
    * **`omron-rs sync --format csv`** — single ISO 8601 `datetime`
      column plus `sys,dia,map,unit,bpm,user_id,status` (see
      [wildcommitter/omron-rs]). The `unit` column is honored:
      kPa rows are auto-converted to mmHg.
  Anything reading `input.csv` should call this rather than
  `pd.read_csv` directly.

  [wildcommitter/omron-rs]: https://github.com/wildcommitter/omron-rs
- **NaN cells** in the PDF tables render as `—`, not `nan`
  (`add_table()` in `_render_pdf.py` handles this).

## Git workflow

- No global `git config` is set. Use `-c user.name=... -c user.email=...`
  on each commit; don't run `git config --global`.
- The commit author for this repo is
  `Wild Committer <guicifuentes88@gmail.com>`.
- Pushes go over SSH via `~/.ssh/id_github`; configured in
  `~/.ssh/config` to be used automatically for `github.com`.
- The `Build container image` workflow runs only on changes to scripts,
  the Containerfile, the entrypoint, or the workflow file itself —
  README-only changes don't trigger a rebuild.

## Don'ts

- Don't try `pip install` against system Python — the host has no `pip`.
- Don't hardcode axis ranges, dates, or row counts that come from data.
- Don't add `input.csv` or any generated artefact to git.
- Don't `git config --global` anything; use `-c` overrides per command.
- Don't skip pre-commit hooks (`--no-verify`) or signing (`--no-gpg-sign`)
  unless explicitly asked — for this repo we set
  `commit.gpgsign=false` per-command because no signing key is set up.
