#!/usr/bin/env bash
# Container entrypoint: runs analyze + report from /data.
set -euo pipefail

# Validate args BEFORE doing any work, so --help and bad args exit fast
# without running the slow analysis.
for arg in "$@"; do
    case $arg in
        --pdf|--md|--markdown) ;;
        -h|--help)
            cat <<EOF
Usage: <image> [--pdf | --md]

Reads /data/input.csv (or copies /input.csv into place first) and writes
the report and intermediate artefacts back to /data.

  --pdf   build report.pdf (default)
  --md    build report.md

Typical invocations:
  podman run --rm -v "\$(pwd):/data:Z" bp-report
  podman run --rm -v "\$(pwd):/data:Z" bp-report --md
  ./bp-report path/to/data.csv          # host-side launcher
EOF
            exit 0
            ;;
        *)
            echo "unknown option: $arg" >&2
            echo "run with --help for usage" >&2
            exit 2
            ;;
    esac
done

# Two ways to provide input:
#   1. /data/input.csv already in the mounted directory.
#   2. /input.csv mounted separately (via the bp-report wrapper).
# If both are present, the explicitly-passed file (/input.csv) wins.
if [[ -f /input.csv ]]; then
    cp /input.csv /data/input.csv
fi

if [[ ! -f /data/input.csv ]]; then
    cat >&2 <<EOF
Error: no input.csv found.

Either mount a directory that already contains input.csv:
    podman run --rm -v "\$(pwd):/data:Z" bp-report

…or use the bp-report launcher to point at any CSV:
    ./bp-report path/to/file.csv [-o output_dir]
EOF
    exit 1
fi

cd /data
python /app/analyze.py
exec env PYTHON_BIN=python WORK_DIR=/data /app/make_report.sh "$@"
