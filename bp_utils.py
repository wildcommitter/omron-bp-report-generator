"""Locale-tolerant reading of OMRON Complete CSV exports.

OMRON exports both column headers and `Fecha`/`Hora` values in whatever
locale the device is configured to use. This module handles both:

  * `parse_dt()` turns a date/time pair into a Timestamp, accepting
    Spanish, English, French, German, Italian, Portuguese and Dutch
    month abbreviations plus ISO 8601 and common numeric formats.
  * `load_omron_csv()` reads a CSV, finds the relevant columns by
    semantic kind (date / time / sys / dia / pulse) regardless of the
    header language, and returns a tidy DataFrame with the standard
    column names `ts`, `sys`, `dia`, `pulse`.
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


# Header patterns for the columns we care about. Match the column-name
# start (anchored with ^) so unit suffixes like "(mmHg)" or "(bpm)" are
# tolerated. Case-insensitive.
_COLUMN_PATTERNS = {
    "date":  r"^\s*(fecha|date|datum|data)\b",
    "time":  r"^\s*(hora|heure|time|uhrzeit|ora|tijd)\b",
    "sys":   r"^\s*(sist[oó]lic|systolic|systolique|systolisch)",
    "dia":   r"^\s*(diast[oó]lic|diastolic|diastolique|diastolisch)",
    "pulse": r"^\s*(puls|pouls|pulso|polso|hartslag)",
}


def find_column(df: pd.DataFrame, kind: str) -> str:
    """Return the actual column name in `df` matching the semantic `kind`."""
    pat = re.compile(_COLUMN_PATTERNS[kind], re.I)
    for col in df.columns:
        if pat.search(str(col)):
            return col
    raise KeyError(
        f"No column matching {kind!r} in CSV header: {list(df.columns)}")


def load_omron_csv(path) -> pd.DataFrame:
    """Read an OMRON Complete CSV in any supported locale into a tidy frame.

    Returns a DataFrame with columns `ts` (Timestamp), `sys`, `dia`, `pulse`
    (int), sorted ascending by `ts`. Non-numeric rows (averages, blanks,
    etc.) are dropped.
    """
    df = pd.read_csv(path)
    cols = {kind: find_column(df, kind)
            for kind in ("date", "time", "sys", "dia", "pulse")}

    sys_numeric = pd.to_numeric(df[cols["sys"]], errors="coerce")
    df = df[sys_numeric.notna()].copy()

    df["ts"] = [parse_dt(d, t)
                for d, t in zip(df[cols["date"]], df[cols["time"]])]
    df = df.rename(columns={cols["sys"]: "sys",
                            cols["dia"]: "dia",
                            cols["pulse"]: "pulse"})
    return (df[["ts", "sys", "dia", "pulse"]]
            .astype({"sys": int, "dia": int, "pulse": int})
            .sort_values("ts")
            .reset_index(drop=True))
