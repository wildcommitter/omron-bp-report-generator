#!/usr/bin/env bash
# Build a vitals report from analysis artefacts.
#   Default:        PDF  (report.pdf)
#   With --md:      Markdown (report.md)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${WORK_DIR:-$SCRIPT_DIR}"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/env/bin/python}"

format=pdf
for arg in "$@"; do
    case $arg in
        --md|--markdown) format=md ;;
        --pdf)           format=pdf ;;
        -h|--help)
            echo "Usage: $0 [--pdf | --md]"
            exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

for f in input.csv vitals.png periods.png periods_weekly.png \
         daily_stats.csv period_stats.csv; do
    [[ -f $f ]] || { echo "missing: $f (run analyze.py first)" >&2; exit 1; }
done

if [[ $format == pdf ]]; then
    exec "$PYTHON_BIN" "$SCRIPT_DIR/_render_pdf.py"
fi

# ---- Markdown path ----
csv2md() {
    awk -F',' '
        NR==1 { printf "|"; for(i=1;i<=NF;i++) printf " %s |", $i; printf "\n|";
                for(i=1;i<=NF;i++) printf "---|"; printf "\n"; next }
              { printf "|"; for(i=1;i<=NF;i++) printf " %s |", $i; printf "\n" }
    ' "$1"
}

read -r N AVG_S AVG_D AVG_P SMIN SMAX DMIN DMAX PMIN PMAX <<<"$(
    awk -F',' 'NR>1 && $3 ~ /^[0-9]+$/ {
        n++; ss+=$3; sd+=$4; sp+=$5
        if(smin==""||$3<smin) smin=$3; if(smax==""||$3>smax) smax=$3
        if(dmin==""||$4<dmin) dmin=$4; if(dmax==""||$4>dmax) dmax=$4
        if(pmin==""||$5<pmin) pmin=$5; if(pmax==""||$5>pmax) pmax=$5
    } END {
        printf "%d %.1f %.1f %.1f %d %d %d %d %d %d", n, ss/n, sd/n, sp/n,
            smin, smax, dmin, dmax, pmin, pmax
    }' input.csv
)"

LATEST=$(awk -F',' 'NR>1 && $3 ~ /^[0-9]+$/ {print $1; exit}' input.csv)
EARLIEST=$(awk -F',' '$3 ~ /^[0-9]+$/ {d=$1} END {print d}' input.csv)
DAYS=$(awk -F',' 'NR>1 && $3 ~ /^[0-9]+$/ {d[$1]=1} END {print length(d)}' \
       input.csv)

cat > report.md <<EOF
# Blood pressure & pulse report

**Source:** \`input.csv\` (OMRON Complete export) · **Range:** ${EARLIEST} → ${LATEST} · **Readings:** ${N} over ${DAYS} days

## Overview

| Metric | Mean | Min | Max |
|---|---:|---:|---:|
| Systolic (mmHg) | ${AVG_S} | ${SMIN} | ${SMAX} |
| Diastolic (mmHg) | ${AVG_D} | ${DMIN} | ${DMAX} |
| Pulse (bpm) | ${AVG_P} | ${PMIN} | ${PMAX} |

## Trend over time

Individual readings, daily mean, and 7-day rolling average. Top-2 spikes per metric annotated.

![Vitals trend](vitals.png)

## Averages by 8-hour period

Three 8h windows starting at 07:00 (morning 07–15, evening 15–23, night 23–07).

$(csv2md period_stats.csv)

![Bar chart of period averages](periods.png)

## Weekly trend by period

Same three periods broken down week-by-week — shows whether the overall downward drift holds at every time of day.

![Weekly period trends](periods_weekly.png)

## Daily statistics

$(csv2md daily_stats.csv)

---
*Generated $(date '+%Y-%m-%d %H:%M') by \`make_report.sh\`.*
EOF

echo "wrote report.md ($(wc -l < report.md) lines)"
