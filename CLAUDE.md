# CLAUDE.md

Context for Claude Code working in this repo.

## What this is

A small data-analysis pipeline for OMRON Complete blood-pressure CSV
exports (Spanish locale: `Fecha`, `Hora`, `Sistólica`, `Diastólica`,
`Pulso`, …). The output is a multi-page PDF (or Markdown) report plus
intermediate CSVs and PNG charts.

## Code layout

- `bp_utils.py` — shared helpers, currently just `parse_dt()` which
  reads Fecha/Hora pairs from any of seven Latin-alphabet locales plus
  ISO/numeric formats. Imported by both `analyze.py` and
  `_render_pdf.py`.
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
- **Locale-tolerant date parsing** lives in `bp_utils.parse_dt()`,
  supporting Spanish / English / French / German / Italian / Portuguese
  / Dutch month abbreviations plus ISO 8601 and numeric formats. Column
  names (`Fecha`, `Hora`, …) are still expected to be Spanish.
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
