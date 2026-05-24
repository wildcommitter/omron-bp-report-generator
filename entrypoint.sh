#!/usr/bin/env bash
# Container entrypoint.  Three modes:
#
#   1. CSV mode (default) — analyse one or more OMRON CSV exports.
#         <image> [CSV_PATH ...] [--pdf | --md]
#
#   2. Daemon mode — stay running, watch for the meter to advertise,
#      pull new records via BLE, merge into /data/input.csv, rebuild.
#         <image> --daemon [--pdf | --md]
#      Needs BP_DEVICE + BP_MAC env vars; optional BP_PAIR_KEY,
#      BP_TIME_SYNC=1.  The container also needs the host's BlueZ DBus
#      socket bind-mounted (the ./bp-report launcher handles that).
#
#   3. Pair mode — one-shot, programs the omblepy pairing key into a
#      meter that's currently in pairing mode.
#         <image> --pair
#      Same BP_DEVICE / BP_MAC / BP_PAIR_KEY env vars.
#
# Relative CSV paths resolve against /data; absolute paths are used as-is.
set -euo pipefail

MODE=csv
CSV_PATHS=()
PASSTHRU=()

for arg in "$@"; do
    case $arg in
        --daemon) MODE=daemon ;;
        --pair)   MODE=pair ;;
        --pdf|--md|--markdown) PASSTHRU+=("$arg") ;;
        -h|--help)
            cat <<EOF
Usage:
  <image> [CSV_PATH ...] [--pdf | --md]      # build a report from CSV(s)
  <image> --daemon [--pdf | --md]            # listen for the BLE meter
  <image> --pair                             # write the pairing key

CSV mode (default): reads input.csv (or any positional CSVs) from /data
and writes report.pdf / report.md next to them.  Multiple paths are
merged with omron_merge.sh before analysis.

Daemon mode: keeps the container alive, scans for BP_MAC's advertisement,
pulls --new-rec-only on every BT-button press, merges into
/data/input.csv, then rebuilds the report.  Env vars:
  BP_DEVICE       hem-7361t / hem-7322t / … (required)
  BP_MAC          XX:XX:XX:XX:XX:XX (required)
  BP_PAIR_KEY     32-hex pairing key (default: upstream omblepy's)
  BP_TIME_SYNC=1  sync the meter's clock each session

Pair mode: same env vars; programs the key, then exits.
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

# Mutual exclusion: --daemon and --pair both read from BLE, not CSV inputs.
if [[ $MODE != csv ]] && [[ ${#CSV_PATHS[@]} -gt 0 ]]; then
    echo "error: --$MODE and CSV positional arguments are mutually exclusive" >&2
    exit 2
fi

bp_required_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        echo "error: --$MODE requires \$$var" >&2
        exit 2
    fi
}

case $MODE in
    pair)
        bp_required_env BP_DEVICE
        bp_required_env BP_MAC
        args=(--device "$BP_DEVICE" --mac "$BP_MAC")
        if [[ -n "${BP_PAIR_KEY:-}" ]]; then
            args+=(--key "$BP_PAIR_KEY")
        fi
        exec /app/omblepy-rs pair "${args[@]}"
        ;;
    daemon)
        bp_required_env BP_DEVICE
        bp_required_env BP_MAC
        # PASSTHRU carries --pdf / --md to make_report.sh inside the rebuild
        # shell command.  Default is --pdf to match the container's CMD.
        if [[ ${#PASSTHRU[@]} -eq 0 ]]; then
            PASSTHRU=(--pdf)
        fi
        REBUILD="python /app/analyze.py && \
PYTHON_BIN=python WORK_DIR=/data /app/make_report.sh ${PASSTHRU[*]}"
        args=(
            --device "$BP_DEVICE"
            --mac "$BP_MAC"
            --merge-target /data/input.csv
            --session-csv /tmp/omblepy-session.csv
            --merge-script /app/omron_merge.sh
            --rebuild-cmd "$REBUILD"
        )
        if [[ -n "${BP_PAIR_KEY:-}" ]]; then
            args+=(--key "$BP_PAIR_KEY")
        fi
        if [[ "${BP_TIME_SYNC:-}" == "1" ]]; then
            args+=(--time-sync)
        fi
        exec /app/omblepy-rs daemon "${args[@]}"
        ;;
    csv)
        if [[ ${#CSV_PATHS[@]} -gt 1 ]]; then
            echo "Merging ${#CSV_PATHS[@]} CSV inputs into /data/input.csv..." >&2
            for p in "${CSV_PATHS[@]}"; do
                if [[ ! -f $p ]]; then
                    echo "error: input file not found: $p" >&2
                    exit 1
                fi
            done
            /app/omron_merge.sh /data/input.csv "${CSV_PATHS[@]}"
        elif [[ ${#CSV_PATHS[@]} -eq 1 ]]; then
            SINGLE="${CSV_PATHS[0]}"
            if [[ ! -f $SINGLE ]]; then
                echo "error: input file not found: $SINGLE" >&2
                exit 1
            fi
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

For BLE direct-from-meter operation, see --daemon and --pair (run with
--help for the env vars they take).
EOF
            exit 1
        fi

        python /app/analyze.py
        exec env PYTHON_BIN=python WORK_DIR=/data /app/make_report.sh "${PASSTHRU[@]}"
        ;;
esac
