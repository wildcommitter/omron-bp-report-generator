#!/usr/bin/env bash
# omron_merge.sh — Combine multiple BP CSVs into one deduplicated CSV.
#
# Usage:
#   ./omron_merge.sh OUTPUT.csv INPUT1.csv INPUT2.csv [INPUT3.csv ...]
#
# Example:
#   ./omron_merge.sh merged.csv exports/*.csv
#
# How it works:
#   1. Validates every input is readable.
#   2. Normalizes each input to the canonical `ts,sys,dia,pulse` schema
#      via `normalize_csv.py` (which delegates to `bp_utils.load_omron_csv`).
#      This lets OMRON Complete app exports and `omron-rs sync --format csv`
#      files be merged in the same call.
#   3. csvstack — vertically concatenates rows (writes ONE header, then all
#      bodies). Header-equality is guaranteed by the normalize pass.
#   4. awk — drops byte-identical duplicate rows while preserving
#      first-occurrence order.
#
# Why not csvjoin?
#   csvjoin performs SQL joins on a key column and produces wide output with
#   suffixed duplicate columns. That is the wrong shape for same-schema
#   measurement exports. csvstack is the csvkit tool meant for this case.
#
# Env vars:
#   PYTHON_BIN — interpreter used for the normalize step
#                (default: ./env/bin/python; container sets this to `python`).
#   SCRIPT_DIR — directory containing normalize_csv.py + bp_utils.py
#                (default: this script's directory).

set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${SELF_DIR}/env/bin/python}"
SCRIPT_DIR="${SCRIPT_DIR:-$SELF_DIR}"

# Make csvstack (from csvkit) findable when running from a conda env on the
# host: env/bin/csvstack lives next to env/bin/python.
PYTHON_DIR="$(dirname "$(command -v "$PYTHON_BIN" || echo "$PYTHON_BIN")")"
case ":$PATH:" in
    *":$PYTHON_DIR:"*) ;;
    *) PATH="$PYTHON_DIR:$PATH" ;;
esac
export PATH

if [[ $# -lt 2 ]]; then
  cat <<USAGE >&2
Usage: $0 OUTPUT.csv INPUT1.csv INPUT2.csv [INPUT3.csv ...]

  At least one input is required, but two or more is the normal case (this
  script's whole point is to merge overlapping exports).
USAGE
  exit 2
fi

OUT="$1"; shift
INPUTS=("$@")

# --- Validate readability ---
for f in "${INPUTS[@]}"; do
  if [[ ! -r "$f" ]]; then
    echo "Cannot read: $f" >&2
    exit 1
  fi
done

# --- Normalize each input to canonical ts,sys,dia,pulse ---
# Different OMRON tooling emits different CSV schemas (Complete app
# export vs omron-rs sync); normalizing first lets us stack them
# regardless of source.
TMPDIR_NORM="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_NORM"' EXIT

NORMALIZED=()
for i in "${!INPUTS[@]}"; do
  N="$TMPDIR_NORM/$(printf 'input_%03d.csv' "$i")"
  "$PYTHON_BIN" "$SCRIPT_DIR/normalize_csv.py" "${INPUTS[$i]}" "$N"
  NORMALIZED+=("$N")
done

# --- Stack + deduplicate ---
# csvstack handles the header collapsing (all normalized files share the
# same canonical header by construction).
# awk '!seen[$0]++' is the classic dedup-preserving-order idiom; we skip line 1
# (the header) so the header itself is always kept.
csvstack "${NORMALIZED[@]}" \
  | awk 'NR==1 { print; next } !seen[$0]++' \
  > "$OUT"

# --- Report ---
n_in_total=0
for f in "${INPUTS[@]}"; do
  n=$(( $(wc -l < "$f") - 1 ))
  n_in_total=$(( n_in_total + n ))
  printf "  %6d rows  %s\n" "$n" "$f" >&2
done
n_out=$(( $(wc -l < "$OUT") - 1 ))

{
  echo "---"
  printf "Merged %d file(s) into %s\n" "${#INPUTS[@]}" "$OUT"
  printf "  total rows in : %d\n" "$n_in_total"
  printf "  rows out      : %d (after dedup)\n" "$n_out"
  printf "  duplicates dropped: %d\n" "$(( n_in_total - n_out ))"
} >&2
