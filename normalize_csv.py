#!/usr/bin/env python
"""Normalize a BP CSV to canonical `ts,sys,dia,pulse` form.

Reads any shape `bp_utils.load_omron_csv` accepts (OMRON Complete app
export or `omron-rs sync --format csv`) and writes the tidy frame as a
plain four-column CSV. Used by `omron_merge.sh` so heterogeneous inputs
share a header before csvstack runs.
"""
from __future__ import annotations

import sys

from bp_utils import load_omron_csv


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: normalize_csv.py INPUT.csv OUTPUT.csv", file=sys.stderr)
        return 2
    df = load_omron_csv(argv[1])
    df.to_csv(argv[2], index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
