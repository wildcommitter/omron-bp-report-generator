"""Locale-tolerant date parsing for OMRON CSV exports.

OMRON Complete exports the `Fecha`/`Hora` cells in whatever locale the
device is configured to use. This module supports the major
Latin-alphabet locales (Spanish, English, French, German, Italian,
Portuguese, Dutch) plus ISO 8601 and common numeric formats — pandas
takes the first crack via `to_datetime`, then a month-alias table
covers the localised abbreviations that dateutil doesn't recognise.

NOTE: column names in the CSV (e.g. "Fecha" vs "Date") are still
expected to be in the original Spanish form. Only the cell *values*
are locale-tolerant here.
"""
from __future__ import annotations

import re
import warnings

import pandas as pd

_MONTH_LOCALES = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul",
           "ago", "sep", "oct", "nov", "dic"],
    "en": ["jan", "feb", "mar", "apr", "may", "jun", "jul",
           "aug", "sep", "oct", "nov", "dec"],
    "fr": ["janv", "févr", "mars", "avr", "mai", "juin", "juil",
           "août", "sept", "oct", "nov", "déc"],
    "de": ["jan", "feb", "mär", "apr", "mai", "jun", "jul",
           "aug", "sep", "okt", "nov", "dez"],
    "it": ["gen", "feb", "mar", "apr", "mag", "giu", "lug",
           "ago", "set", "ott", "nov", "dic"],
    "pt": ["jan", "fev", "mar", "abr", "mai", "jun", "jul",
           "ago", "set", "out", "nov", "dez"],
    "nl": ["jan", "feb", "mrt", "apr", "mei", "jun", "jul",
           "aug", "sep", "okt", "nov", "dec"],
}

# Flat alias → month number map. Overlaps across locales must all resolve
# to the same month (e.g. "feb" = 2 in every supported locale) — verified
# at import time so a typo in the table doesn't silently misparse data.
MONTH_ALIASES: dict[str, int] = {}
for _months in _MONTH_LOCALES.values():
    for _i, _name in enumerate(_months, 1):
        _prev = MONTH_ALIASES.get(_name)
        if _prev is not None and _prev != _i:
            raise RuntimeError(
                f"month alias conflict: {_name!r} → {_prev} vs {_i}")
        MONTH_ALIASES[_name] = _i

_PUNCT = re.compile(r"[.,]")


def parse_dt(date_str: str, time_str: str) -> pd.Timestamp:
    """Parse a `Fecha`/`Hora` pair from any supported locale.

    Tries `pandas.to_datetime` first (catches ISO 8601, English, and
    common numeric formats). On failure, falls back to a month-alias
    lookup that handles localised abbreviations dateutil rejects
    ("mär.", "févr.", "mai", "ene.", …).
    """
    full = f"{date_str} {time_str}".strip()
    with warnings.catch_warnings():
        # pandas warns when an ISO-shaped string is paired with dayfirst=True;
        # the result is still correct, but the warning is noise here.
        warnings.simplefilter("ignore", UserWarning)
        iso = pd.to_datetime(full, dayfirst=True, errors="coerce")
    if pd.notna(iso):
        return iso

    parts = _PUNCT.sub(" ", date_str).split()
    month = None
    nums: list[int] = []
    for tok in parts:
        key = tok.lower()
        if key in MONTH_ALIASES and month is None:
            month = MONTH_ALIASES[key]
        elif tok.isdigit():
            nums.append(int(tok))

    if month is None or len(nums) != 2:
        raise ValueError(f"Could not parse date {date_str!r}")

    # Heuristic: the larger number is the year, the smaller is the day.
    day, year = sorted(nums)
    if year < 100:
        year += 2000
    hh, mm = map(int, time_str.split(":"))
    return pd.Timestamp(year, month, day, hh, mm)
