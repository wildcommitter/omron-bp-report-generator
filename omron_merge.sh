#!/usr/bin/env bash
# omron_merge.sh — Combine multiple OMRON blood-pressure CSV exports into one
# deduplicated CSV.
#
# Usage:
#   ./omron_merge.sh OUTPUT.csv INPUT1.csv INPUT2.csv [INPUT3.csv ...]
#
# Example:
#   ./omron_merge.sh merged.csv exports/*.csv
#
# How it works:
#   1. Validates every input is readable and shares the same header schema.
#   2. csvstack — vertically concatenates rows (writes ONE header, then all bodies).
#   3. awk — drops byte-identical duplicate rows while preserving first-occurrence
#      order, which keeps the OMRON convention of newest-first when the input
#      with the most recent end-date is listed first.
#
# Why not csvjoin?
#   csvjoin performs SQL joins on a key column and produces wide output with
#   suffixed duplicate columns ("Sistólica_2", "Sistólica_3", …). That is the
#   wrong shape for same-schema measurement exports. csvstack is the csvkit
#   tool meant for this case.

set -euo pipefail

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

# --- Validate schema: all headers must match the first file's header ---
H_REF="$(head -n1 "${INPUTS[0]}")"
for f in "${INPUTS[@]:1}"; do
  H_OTHER="$(head -n1 "$f")"
  if [[ "$H_REF" != "$H_OTHER" ]]; then
    {
      echo "Header mismatch in: $f"
      echo "  expected: $H_REF"
      echo "  got:      $H_OTHER"
    } >&2
    exit 1
  fi
done

# --- Stack + deduplicate ---
# csvstack handles the header collapsing.
# awk '!seen[$0]++' is the classic dedup-preserving-order idiom; we skip line 1
# (the header) so the header itself is always kept.
csvstack "${INPUTS[@]}" \
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
