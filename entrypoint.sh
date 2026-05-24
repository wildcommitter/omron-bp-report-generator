#!/usr/bin/env bash
# Container entrypoint: runs analyze + report from /data.
#
# Usage inside the container:
#   <image> [CSV_PATH ...] [--pdf | --md]
#
# Zero, one, or many CSV paths may be given:
#   - 0 paths: expects /data/input.csv to be present (e.g. via volume mount)
#   - 1 path:  copied to /data/input.csv
#   - N paths: merged + deduplicated into /data/input.csv via omron_merge.sh
#
# Relative paths resolve against /data; absolute paths are used as-is.
set -euo pipefail

CSV_PATHS=()
PASSTHRU=()

for arg in "$@"; do
    case $arg in
        --pdf|--md|--markdown) PASSTHRU+=("$arg") ;;
        -h|--help)
            cat <<EOF
Usage: <image> [CSV_PATH ...] [--pdf | --md]

Reads one or more input CSVs and writes the report + intermediate
artefacts to /data.  When multiple CSV paths are given, they are
merged (csvstack + dedup) into /data/input.csv before analysis.

  CSV_PATH    one or more OMRON CSV exports (relative paths resolve
              in /data).  If omitted, /data/input.csv is used.
  --pdf       build report.pdf (default)
  --md        build report.md

Examples:
  podman run --rm -v "\$(pwd):/data:Z" bp-report
  podman run --rm -v "\$(pwd):/data:Z" bp-report my_readings.csv --md
  ./bp-report a.csv b.csv c.csv -o out/   # host-side launcher
EOF
            exit 0
            ;;
        -*)
            echo "unknown option: $arg" >&2
            echo "run with --help for usage" >&2
            exit 2
            ;;
        *)
            CSV_PATHS+=("$arg")
            ;;
    esac
done

cd /data

if [[ ${#CSV_PATHS[@]} -gt 1 ]]; then
    echo "Merging ${#CSV_PATHS[@]} CSV inputs into /data/input.csv..." >&2
    for p in "${CSV_PATHS[@]}"; do
        if [[ ! -f $p ]]; then
            echo "error: input file not found: $p" >&2
            exit 1
        fi
    done
    env PYTHON_BIN=python SCRIPT_DIR=/app \
        /app/omron_merge.sh /data/input.csv "${CSV_PATHS[@]}"
elif [[ ${#CSV_PATHS[@]} -eq 1 ]]; then
    SINGLE="${CSV_PATHS[0]}"
    if [[ ! -f $SINGLE ]]; then
        echo "error: input file not found: $SINGLE" >&2
        exit 1
    fi
    # Copy into /data/input.csv unless the source already IS that file.
    if ! [[ $SINGLE -ef /data/input.csv ]]; then
        cp "$SINGLE" /data/input.csv
    fi
elif [[ ! -f /data/input.csv ]]; then
    cat >&2 <<EOF
Error: no input CSV found.

Either mount a directory containing input.csv:
    podman run --rm -v "\$(pwd):/data:Z" bp-report

…pass one or more CSV paths explicitly:
    podman run --rm -v "\$(pwd):/data:Z" bp-report my_readings.csv
    podman run --rm -v "\$(pwd):/data:Z" bp-report a.csv b.csv c.csv

…or use the host-side launcher:
    ./bp-report path/to/file.csv [more.csv ...] [-o output_dir]
EOF
    exit 1
fi

python /app/analyze.py
exec env PYTHON_BIN=python WORK_DIR=/data /app/make_report.sh "${PASSTHRU[@]}"
