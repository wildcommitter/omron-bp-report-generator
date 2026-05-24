# BP report

Analysis pipeline for an OMRON Complete blood-pressure export. Reads
`input.csv`, computes daily / period / weekly statistics, renders charts,
and assembles a PDF (or Markdown) report.

## Setup

A conda env lives in `./env`. Activate it or call binaries directly:

```
conda activate ./env
# or
./env/bin/python analyze.py
```

The env was created with:

```
~/anaconda3/bin/conda create -p ./env python=3.13 \
    matplotlib pandas numpy scipy seaborn jupyter
```

## Usage

### Local (conda env)

```
./env/bin/python analyze.py   # regenerate stats CSVs and PNGs
./make_report.sh              # build report.pdf (default)
./make_report.sh --md         # build report.md instead
```

`make_report.sh` re-derives summary stats from `input.csv` via `awk` and
calls `_render_pdf.py` (which uses `matplotlib.PdfPages`) for the PDF path.

### Container (podman)

Build once:

```
podman build -t bp-report .
```

The recommended way to run is via the `bp-report` launcher, which takes
any CSV path as an argument and handles the volume mounts for you:

```
./bp-report path/to/data.csv                      # report in same dir as data.csv
./bp-report path/to/data.csv -o /some/out/dir     # outputs into a different dir
./bp-report path/to/data.csv --md                 # Markdown instead of PDF
```

A copy of the source CSV ends up alongside the report (renamed to
`input.csv`) so each output directory is self-contained.

You can also drop down to raw podman. The entrypoint accepts an optional
CSV path so the source file doesn't have to be named `input.csv`:

```
podman run --rm -v "$(pwd):/data:Z" bp-report                       # /data/input.csv → PDF
podman run --rm -v "$(pwd):/data:Z" bp-report --md                  # /data/input.csv → MD
podman run --rm -v "$(pwd):/data:Z" bp-report my_readings.csv       # /data/my_readings.csv → PDF
podman run --rm -v "$(pwd):/data:Z" bp-report my_readings.csv --md  # both options together
```

Relative paths resolve inside `/data`. The CSV path and `--pdf`/`--md`
can appear in any order. The image bundles the scripts, Python deps,
and the `omblepy-rs` Rust binary that talks BLE to the meter (~500 MB
total) — no conda env, no source data.

### Direct from the meter (BLE)

Skip the phone export. The image bundles `omblepy-rs`, a Rust port of
[`userx14/omblepy`](https://github.com/userx14/omblepy) that speaks
the Omron BLE protocol directly. First time, pair the meter:

```
./bp-report --pair --device hem-7361t --mac AA:BB:CC:DD:EE:FF
```

(swap the model for your meter; `omblepy-rs list-devices` shows all
nine supported models). Then run the daemon:

```
./bp-report --daemon --device hem-7361t --mac AA:BB:CC:DD:EE:FF
```

The container stays running. Every time you press the BT button on
the meter it scans, connects, pulls only the unread records, merges
them into `input.csv`, and rebuilds the report. Ctrl-C to stop.

Both BLE modes need access to the host's BlueZ daemon; the launcher
adds `--net=host` and bind-mounts `/run/dbus` automatically.

### Pulling the prebuilt image

Each push to `main` and every `v*` tag triggers
`.github/workflows/build-image.yml`, which builds the image with Buildah
and pushes it to GitHub Container Registry. The image is public, so no
login is needed:

```
podman pull ghcr.io/wildcommitter/omron-bp-report-generator:latest
BP_REPORT_IMAGE=ghcr.io/wildcommitter/omron-bp-report-generator:latest \
    ./bp-report data.csv
```

The launcher honors `$BP_REPORT_IMAGE` so you can point it at any tag
(`latest`, `sha-<short>`, `v1.2.3`, etc.) without rebuilding locally.

The same scripts respect two env vars so the container can override paths
without duplicating code:

- `WORK_DIR` — where `input.csv` lives and outputs go (default: script dir).
- `PYTHON_BIN` — interpreter for `_render_pdf.py` (default: `./env/bin/python`).

## Inputs

- `input.csv` — OMRON Complete export (Spanish locale: `Fecha`, `Hora`,
  `Sistólica`, `Diastólica`, `Pulso`, …).

## Generated artefacts

| File | Contents |
|---|---|
| `vitals.png` / `vitals.pdf` | Three-panel time series (sys/dia/pulse) with daily mean, 7-day rolling average, top-2 spikes annotated. |
| `periods.png` | Bar chart of overall averages by 8-hour period (Morning 07–15, Evening 15–23, Night 23–07) with whiskers. |
| `periods_weekly.png` | Per-week, per-period line plot for each metric. |
| `daily_stats.csv` | 31 daily rows × 22 cols: mean/min/max + AM/PM/Nt + 7-day rolling for each of sys, dia, pulse. |
| `period_stats.csv` | Overall mean/min/max per 8-hour period. |
| `weekly_period_stats.csv` | Per (week, period) means with week-over-week deltas. |
| `report.pdf` | 6-page report: cover, trend, weekly period breakdown, weekly trend chart, daily BP table, daily pulse table. |
| `report.md` | Same content as Markdown when invoked with `--md`. |

## File layout

```
input.csv               source data
analyze.py              stats + chart generation
make_report.sh          report orchestrator (--pdf default | --md)
_render_pdf.py          matplotlib PdfPages composer
entrypoint.sh           container entrypoint — CSV / --daemon / --pair
bp-report               host-side launcher: CSV inputs OR --daemon / --pair
omblepy-rs/             Rust port of omblepy — BLE client for Omron meters
omron_merge.sh          csvkit-based dedupe-merge for CSV inputs
Containerfile           multi-stage: rust-builder → python:3.13-slim
.containerignore        excludes env/ and outputs from build context
env/                    project-local conda env (Python 3.13)
README.md               this file
```

## Notes

- All chart y-axis ranges are derived from the data via an `autoscale()`
  helper, so a different input CSV adapts automatically.
- The 8-hour day partition is hard-coded to start at 07:00. Edit the
  `period()` function in `analyze.py` to shift the boundaries.
- Hypertension band thresholds (120/130/140 mmHg sys, 80/90 dia, 100 bpm)
  are clinical constants and stay fixed regardless of data.
- Reports are not medical advice.
