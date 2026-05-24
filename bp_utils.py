"""Locale-tolerant reading of blood-pressure CSV exports.

Two input shapes are supported:

  * **OMRON Complete app export** — separate `Fecha`/`Hora` columns
    in the device's configured locale (Spanish/English/French/German/
    Italian/Portuguese/Dutch month abbreviations, plus ISO 8601 and
    common numeric formats). Pulse is `Pulso (ppm)` or the localised
    equivalent.
  * **`omron-rs sync --format csv`** — single ISO 8601 `datetime`
    column with `sys,dia,map,unit,bpm,user_id,status` alongside it
    (see https://github.com/wildcommitter/omron-rs). Pulse column
    is `bpm`. Rows in kPa are auto-converted to mmHg.

`load_omron_csv()` returns a tidy DataFrame with the standard column
names `ts`, `sys`, `dia`, `pulse` regardless of which shape the input
file has.
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
    "datetime": r"^\s*(datetime|date[_\- ]?time|timestamp|ts)\s*$",
    "date":  r"^\s*(fecha|date|datum|data)\b",
    "time":  r"^\s*(hora|heure|time|uhrzeit|ora|tijd)\b",
    "sys":   r"^\s*(sist[oó]lic|systolic|systolique|systolisch|sys\b)",
    "dia":   r"^\s*(diast[oó]lic|diastolic|diastolique|diastolisch|dia\b)",
    "pulse": r"^\s*(puls|pouls|pulso|polso|hartslag|bpm|heart)",
    "unit":  r"^\s*unit\s*$",
}

_KPA_TO_MMHG = 7.50062


def find_column(df: pd.DataFrame, kind: str) -> str:
    """Return the actual column name in `df` matching the semantic `kind`."""
    pat = re.compile(_COLUMN_PATTERNS[kind], re.I)
    for col in df.columns:
        if pat.search(str(col)):
            return col
    raise KeyError(
        f"No column matching {kind!r} in CSV header: {list(df.columns)}")


def _maybe_find(df: pd.DataFrame, kind: str) -> str | None:
    try:
        return find_column(df, kind)
    except KeyError:
        return None


def load_omron_csv(path) -> pd.DataFrame:
    """Read a blood-pressure CSV into a tidy frame.

    Accepts both the OMRON Complete app export (locale-aware
    `Fecha`/`Hora`) and `omron-rs sync --format csv` (ISO 8601
    `datetime`). Returns columns `ts` (Timestamp), `sys`, `dia`,
    `pulse` (int), sorted ascending by `ts`. Rows with non-numeric
    sys/dia/pulse or unparseable timestamps are dropped.
    """
    df = pd.read_csv(path)
    sys_col = find_column(df, "sys")
    dia_col = find_column(df, "dia")
    pulse_col = find_column(df, "pulse")
    dt_col = _maybe_find(df, "datetime")

    if dt_col is not None:
        ts = pd.to_datetime(df[dt_col], errors="coerce", utc=False)
    else:
        date_col = find_column(df, "date")
        time_col = find_column(df, "time")
        ts = pd.Series(
            [parse_dt(d, t) if pd.notna(d) and pd.notna(t) else pd.NaT
             for d, t in zip(df[date_col], df[time_col])],
            index=df.index,
        )

    sys = pd.to_numeric(df[sys_col], errors="coerce")
    dia = pd.to_numeric(df[dia_col], errors="coerce")
    pulse = pd.to_numeric(df[pulse_col], errors="coerce")

    unit_col = _maybe_find(df, "unit")
    if unit_col is not None:
        kpa = df[unit_col].astype(str).str.strip().str.lower().eq("kpa")
        if kpa.any():
            sys = sys.mask(kpa, sys * _KPA_TO_MMHG)
            dia = dia.mask(kpa, dia * _KPA_TO_MMHG)

    out = pd.DataFrame({"ts": ts, "sys": sys, "dia": dia, "pulse": pulse})
    out = out.dropna(subset=["ts", "sys", "dia", "pulse"])
    return (out.astype({"sys": int, "dia": int, "pulse": int})
            .sort_values("ts")
            .reset_index(drop=True))
