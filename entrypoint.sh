#!/usr/bin/env bash
# Container entrypoint: runs analyze + report from /data.
#
# Usage inside the container:
#   <image> [CSV_PATH] [--pdf | --md]
#
# CSV_PATH is optional. Relative paths resolve against /data; absolute paths
# are used as-is. If omitted, /data/input.csv is expected to be present.
set -euo pipefail

INPUT_PATH=""
PASSTHRU=()

for arg in "$@"; do
    case $arg in
        --pdf|--md|--markdown) PASSTHRU+=("$arg") ;;
        -h|--help)
            cat <<EOF
Usage: <image> [CSV_PATH] [--pdf | --md]

Reads the input CSV and writes the report + intermediate artefacts to /data.

  CSV_PATH    path to the OMRON CSV (relative paths resolve in /data).
              If omitted, /data/input.csv is used.
  --pdf       build report.pdf (default)
  --md        build report.md

Examples:
  podman run --rm -v "\$(pwd):/data:Z" bp-report
  podman run --rm -v "\$(pwd):/data:Z" bp-report my_readings.csv --md
  ./bp-report path/to/data.csv          # host-side launcher
EOF
            exit 0
            ;;
        -*)
            echo "unknown option: $arg" >&2
            echo "run with --help for usage" >&2
            exit 2
            ;;
        *)
            if [[ -n $INPUT_PATH ]]; then
                echo "error: multiple CSV paths given ($INPUT_PATH, $arg)" >&2
                exit 2
            fi
            INPUT_PATH=$arg
            ;;
    esac
done

cd /data

if [[ -n $INPUT_PATH ]]; then
    if [[ ! -f $INPUT_PATH ]]; then
        echo "error: input file not found: $INPUT_PATH" >&2
        exit 1
    fi
    # Copy into /data/input.csv unless the source already IS that file.
    if ! [[ $INPUT_PATH -ef /data/input.csv ]]; then
        cp "$INPUT_PATH" /data/input.csv
    fi
elif [[ ! -f /data/input.csv ]]; then
    cat >&2 <<EOF
Error: no input CSV found.

Either mount a directory containing input.csv:
    podman run --rm -v "\$(pwd):/data:Z" bp-report

…pass the CSV path explicitly:
    podman run --rm -v "\$(pwd):/data:Z" bp-report my_readings.csv

…or use the host-side launcher:
    ./bp-report path/to/file.csv [-o output_dir]
EOF
    exit 1
fi

python /app/analyze.py
exec env PYTHON_BIN=python WORK_DIR=/data /app/make_report.sh "${PASSTHRU[@]}"
