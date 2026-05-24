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
- `bp-report` — host-side launcher around `podman run`. Three modes:
  CSV (the default — takes one or more OMRON exports and writes a
  report), `--daemon` (long-running BLE listener, see below), and
  `--pair` (one-shot pairing of a fresh meter). Handles the DBus
  bind-mounts the BLE modes need.
- `entrypoint.sh` — container entrypoint. Branches on `--daemon` /
  `--pair` / CSV positional args. Validates args before running.
- `Containerfile` — multi-stage: stage 1 (`rust:1-slim-bookworm`) builds
  `omblepy-rs`; stage 2 (`python:3.13-slim`) bundles the scripts +
  binary + `libdbus-1-3` + `bluez` for runtime DBus.
- `omblepy-rs/` — Rust port of [`userx14/omblepy`](https://github.com/userx14/omblepy).
  Compiled with `bluer`; talks to Omron BLE blood-pressure meters over
  the host's BlueZ DBus. Subcommands: `list-devices`, `scan`, `pair`,
  `dump` (one-shot), `daemon` (listener loop). All 9 upstream device
  drivers ported. Writes the Spanish 17-column OMRON-Complete CSV
  schema so `omron_merge.sh` can stack a daemon-written file alongside
  a hand-exported one.
- `.github/workflows/build-image.yml` — buildah/podman GitHub Action
  that publishes to `ghcr.io/wildcommitter/omron-bp-report-generator`.
- `.github/workflows/release-arch.yml` — fires on `v*` tag push.
  Builds an Arch `.pkg.tar.zst` containing the launcher (pointed at the
  matching GHCR tag) and attaches it to the GitHub Release.
- `packaging/arch/PKGBUILD` — recipe consumed by the release workflow.
  `pkgver` is the literal token `__PKGVER__`; the workflow substitutes
  the git tag before calling `makepkg`.

## Running things

```
./env/bin/python analyze.py        # regenerate stats + PNGs
./make_report.sh                   # build report.pdf
./make_report.sh --md              # build report.md instead
./bp-report path/to/file.csv       # CSV mode via container
./bp-report --pair --device hem-7361t --mac AA:BB:CC:DD:EE:FF  # first-time BLE setup
./bp-report --daemon --device hem-7361t --mac AA:BB:CC:DD:EE:FF  # listen for the meter
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
  which handles both the date *values* (Spanish / English / French /
  German / Italian / Portuguese / Dutch month abbreviations + ISO 8601 +
  numeric formats) and the *column headers* (Fecha/Date/Datum/Data,
  Sistólica/Systolic/Systolique/…). Anything reading `input.csv`
  should call this rather than `pd.read_csv` directly.
- **NaN cells** in the PDF tables render as `—`, not `nan`
  (`add_table()` in `_render_pdf.py` handles this).
- **Bluetooth in the container** — `--daemon` and `--pair` need the
  host's BlueZ available inside. The launcher handles this by adding
  `--net=host` and bind-mounting `/run/dbus` (or `/var/run/dbus` on
  older hosts). No bluetooth-daemon inside the container — it talks
  to the host's via DBus.
- **CSV emit format** — `omblepy-rs` writes the **full 17-column**
  OMRON Complete schema (the same `Fecha,Hora,Sistólica (mmHg),…`
  header the user's existing `input.csv` carries), not just the five
  columns `bp_utils.load_omron_csv` reads. Header parity is what lets
  `omron_merge.sh` stack a daemon-written file against a hand-exported
  one — the script enforces exact-header equality.
- **Pairing key** — default is upstream omblepy's
  `deadbeaf12341234deadbeaf12341234`. Meters paired with the Python
  tool keep working with no re-pair. Override with `--pair-key HEX`
  on the launcher, or `BP_PAIR_KEY` in the env.

## Cutting a release

```
git tag -a v0.3.0 -m 'release notes here'
git push origin v0.3.0
```

That fires two workflows in parallel:

- `build-image.yml` — pushes
  `ghcr.io/wildcommitter/omron-bp-report-generator:v0.3.0` (plus the
  rolling `latest` tag).
- `release-arch.yml` — creates the matching GitHub Release with
  auto-generated notes, builds `bp-report-0.3.0-1-any.pkg.tar.zst`,
  and uploads it as a release asset.

The PKGBUILD points the installed launcher at the GHCR image of the
same tag, so a user `pacman -U`-ing the asset is automatically wired
up to the matching container build.

`workflow_dispatch` on `release-arch.yml` is available for testing the
package build without cutting a tag — it produces a date-stamped
dev `.pkg.tar.zst` as a workflow artifact only (no release upload).

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
- Don't run `cargo` on the host — there's no Rust toolchain installed.
  Compile + test `omblepy-rs` via `podman build --target rust-builder`
  (compile-only) or a one-off `cargo test` Containerfile.
