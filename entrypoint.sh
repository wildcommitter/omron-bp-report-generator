#!/usr/bin/env bash
# Container entrypoint: runs analyze + report from /data.
set -euo pipefail

# Two ways to provide input:
#   1. /data/input.csv already in the mounted directory.
#   2. /input.csv mounted separately (via the bp-report wrapper).
# If both, the explicitly-passed file (/input.csv) wins.
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
PYTHON_BIN=python WORK_DIR=/data /app/make_report.sh "$@"
