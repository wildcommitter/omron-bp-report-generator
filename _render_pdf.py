#!/usr/bin/env python3
"""Compose report.pdf from analysis artefacts using matplotlib PdfPages."""
from datetime import datetime
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from bp_utils import load_omron_csv

HERE = Path.cwd()

df = load_omron_csv(HERE / "input.csv")

t0, t1 = df["ts"].min(), df["ts"].max()
days = df["ts"].dt.date.nunique()

period_stats = pd.read_csv(HERE / "period_stats.csv")
daily_stats = pd.read_csv(HERE / "daily_stats.csv")
weekly_period = pd.read_csv(HERE / "weekly_period_stats.csv")

# Shorter, non-overlapping column names for tables
PERIOD_COLS = {
    "period": "Period", "readings": "n",
    "sys_mean": "Sys", "sys_min": "Sys−", "sys_max": "Sys+",
    "dia_mean": "Dia", "dia_min": "Dia−", "dia_max": "Dia+",
    "pulse_mean": "Pulse", "pulse_min": "Plse−", "pulse_max": "Plse+",
}
DAILY_COLS = {
    "date": "Date", "readings": "n",
    "sys_mean": "Sys", "sys_min": "S−", "sys_max": "S+",
    "sys_morn": "S AM", "sys_eve": "S PM", "sys_night": "S Nt",
    "sys_7d_avg": "S 7d",
    "dia_mean": "Dia", "dia_min": "D−", "dia_max": "D+",
    "dia_morn": "D AM", "dia_eve": "D PM", "dia_night": "D Nt",
    "dia_7d_avg": "D 7d",
    "pulse_mean": "Pls", "pulse_min": "P−", "pulse_max": "P+",
    "pulse_morn": "P AM", "pulse_eve": "P PM", "pulse_night": "P Nt",
    "pulse_7d_avg": "P 7d",
}
period_stats = period_stats.rename(columns=PERIOD_COLS)
period_stats["Period"] = (period_stats["Period"]
    .str.replace(r"^\d+\.\s*", "", regex=True)
    .str.replace(r"\s*\(.*\)$", "", regex=True)
    .str.capitalize())
daily_stats = daily_stats.rename(columns=DAILY_COLS)

PERIOD_WIDTHS = [0.16, 0.06, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08]

# Weekly breakdown — one row per (week, period), with Δ vs same period prior week
def fmt_delta(v):
    if pd.isna(v):
        return "—"
    return f"{v:+.1f}".replace("+0.0", "0.0")

_period_short = {"1. morning (07–15)": "Morning",
                 "2. evening (15–23)": "Evening",
                 "3. night (23–07)":   "Night"}
weekly_period["week_start"] = pd.to_datetime(weekly_period["week_start"])
weekly_period = weekly_period.sort_values(["week_start", "period"])
_wp_rows = []
_last_week = None
for _, row in weekly_period.iterrows():
    week_label = (row["week_start"].strftime("%d %b")
                  if row["week_start"] != _last_week else "")
    _wp_rows.append([
        week_label,
        _period_short[row["period"]],
        int(row["n"]),
        f"{row['sys']:.1f}", fmt_delta(row["d_sys"]),
        f"{row['dia']:.1f}", fmt_delta(row["d_dia"]),
        f"{row['pulse']:.1f}", fmt_delta(row["d_pulse"]),
    ])
    _last_week = row["week_start"]
weekly_period_table = pd.DataFrame(_wp_rows, columns=[
    "Week of", "Period", "n",
    "Sys", "Δ Sys", "Dia", "Δ Dia", "Pulse", "Δ Pulse",
])
WEEKLY_PERIOD_WIDTHS = [0.10, 0.09, 0.05, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08]
SYS_COLS = ["Sys", "S−", "S+", "S AM", "S PM", "S Nt", "S 7d"]
DIA_COLS = ["Dia", "D−", "D+", "D AM", "D PM", "D Nt", "D 7d"]
PLS_COLS = ["Pls", "P−", "P+", "P AM", "P PM", "P Nt", "P 7d"]
BP_WIDTHS = [0.07, 0.03] + [0.055] * 14    # Date, n, 14 sys/dia cols
PLS_WIDTHS = [0.10, 0.05] + [0.11] * 7     # Date, n, 7 pulse cols

LANDSCAPE = (11, 8.5)
PORTRAIT = (8.5, 11)

def new_page(pdf, title, size=LANDSCAPE):
    fig = plt.figure(figsize=size)
    fig.text(0.5, 0.95, title, ha="center", va="top",
             fontsize=18, fontweight="bold")
    fig.text(0.5, 0.91,
             f"{t0:%d %b %Y} → {t1:%d %b %Y}  ·  "
             f"{len(df)} readings  ·  {days} days",
             ha="center", va="top", fontsize=10, color="#555")
    return fig

def add_image(fig, path, top=0.86, bottom=0.06):
    """Place an image centered in the band [bottom, top], aspect-preserved."""
    img = mpimg.imread(path)
    h, w = img.shape[:2]
    aspect = h / w
    page_w, page_h = fig.get_size_inches()
    avail_w, avail_h = 0.92, top - bottom
    # Try to fill width first
    width = avail_w
    height = width * aspect * page_w / page_h
    if height > avail_h:
        height = avail_h
        width = height * page_h / (aspect * page_w)
    left = (1 - width) / 2
    band_center = bottom + avail_h / 2
    img_bottom = band_center - height / 2
    ax = fig.add_axes([left, img_bottom, width, height])
    ax.imshow(img)
    ax.axis("off")

def add_table(fig, df_, top=0.86, bottom=0.08, fontsize=9, col_widths=None,
              row_scale=1.4, header_color="#1f3a5f", row_alt="#f3f5f8"):
    formatted = df_.copy()
    for c in formatted.columns:
        formatted[c] = formatted[c].apply(
            lambda v: "—" if (isinstance(v, float) and pd.isna(v)) else v)
    rows = formatted.astype(str).values.tolist()
    cols = list(formatted.columns)
    ax = fig.add_axes([0.04, bottom, 0.92, top - bottom])
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=cols, loc="upper center",
                     cellLoc="center", colLoc="center",
                     colWidths=col_widths)
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)
    table.scale(1, row_scale)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#cccccc")
        if r == 0:
            cell.set_facecolor(header_color)
            cell.set_text_props(color="white", weight="bold")
        elif r % 2 == 0:
            cell.set_facecolor(row_alt)

out = HERE / "report.pdf"
pages = 0
with PdfPages(out) as pdf:
    # Cover (portrait)
    fig = new_page(pdf, "Blood pressure & pulse report", size=PORTRAIT)
    fig.text(0.5, 0.85, "Source: input.csv (OMRON Complete export)",
             ha="center", fontsize=10, style="italic", color="#666")
    fig.text(0.5, 0.78, "Overview", ha="center", fontsize=14,
             fontweight="bold")
    summary = pd.DataFrame({
        "Metric":  ["Systolic (mmHg)", "Diastolic (mmHg)", "Pulse (bpm)"],
        "Mean":    [f"{df['sys'].mean():.1f}", f"{df['dia'].mean():.1f}",
                    f"{df['pulse'].mean():.1f}"],
        "Min":     [df["sys"].min(), df["dia"].min(), df["pulse"].min()],
        "Max":     [df["sys"].max(), df["dia"].max(), df["pulse"].max()],
        "Std dev": [f"{df['sys'].std():.1f}", f"{df['dia'].std():.1f}",
                    f"{df['pulse'].std():.1f}"],
    })
    add_table(fig, summary, top=0.76, bottom=0.58, fontsize=11,
              col_widths=[0.32, 0.13, 0.11, 0.11, 0.15])
    fig.text(0.5, 0.46,
             f"Generated {datetime.now():%Y-%m-%d %H:%M}",
             ha="center", fontsize=9, color="#888")
    pdf.savefig(fig); plt.close(fig); pages += 1

    # Trend over time (landscape)
    fig = new_page(pdf, "Trend over time")
    fig.text(0.5, 0.875,
             "Individual readings, daily mean, 7-day rolling average. "
             "Top-2 spikes per metric annotated.",
             ha="center", fontsize=9, color="#555")
    add_image(fig, HERE / "vitals.png", top=0.85, bottom=0.04)
    pdf.savefig(fig); plt.close(fig); pages += 1

    # 8h period averages — weekly breakdown with Δ vs previous week
    fig = new_page(pdf, "Averages by 8-hour period — weekly")
    fig.text(0.5, 0.875,
             "Each week's average per period, with Δ vs same period the "
             "prior week. Morning 07–15 · Evening 15–23 · Night 23–07.",
             ha="center", fontsize=9, color="#555")
    add_table(fig, weekly_period_table, top=0.85, bottom=0.04,
              fontsize=8, col_widths=WEEKLY_PERIOD_WIDTHS, row_scale=1.2)
    pdf.savefig(fig); plt.close(fig); pages += 1

    # Weekly trend (landscape)
    fig = new_page(pdf, "Weekly trend by 8-hour period")
    add_image(fig, HERE / "periods_weekly.png", top=0.88, bottom=0.06)
    pdf.savefig(fig); plt.close(fig); pages += 1

    # Diurnal (24-hour) pattern with morning-surge summary
    diurnal_csv = HERE / "hourly_stats.csv"
    if diurnal_csv.exists() and (HERE / "diurnal.png").exists():
        hourly = pd.read_csv(diurnal_csv).set_index("hour")
        def _surge_summary(m):
            pre = hourly.loc[hourly.index < 6, f"{m}_mean"]
            morn = hourly.loc[(hourly.index >= 6) & (hourly.index <= 10),
                              f"{m}_mean"]
            if pre.empty or morn.empty:
                return "—"
            return (f"+{morn.max() - pre.min():.1f}  "
                    f"(min {pre.min():.0f} @ {int(pre.idxmin()):02d}h → "
                    f"max {morn.max():.0f} @ {int(morn.idxmax()):02d}h)")

        fig = new_page(pdf, "Diurnal pattern by hour of day")
        fig.text(0.5, 0.875,
                 "Hourly mean (± IQR) across all days; bottom row = sample "
                 "count per hour. Morning surge proxy = peak 06–10h − "
                 "trough 00–06h.",
                 ha="center", fontsize=9, color="#555")
        # Morning-surge proxy as a small left-aligned block
        surge_lines = [
            f"Sys    {_surge_summary('sys')}",
            f"Dia    {_surge_summary('dia')}",
            f"Pulse  {_surge_summary('pulse')}",
        ]
        for i, line in enumerate(surge_lines):
            fig.text(0.06, 0.83 - i * 0.022, line,
                     fontsize=8.5, color="#1f3a5f", fontweight="bold",
                     family="monospace")
        add_image(fig, HERE / "diurnal.png", top=0.78, bottom=0.04)
        pdf.savefig(fig); plt.close(fig); pages += 1

    # Daily statistics — split across two landscape pages:
    #   Page A: Sys + Dia blocks (Date, n, 14 BP cols)
    #   Page B: Pulse block      (Date, n, 7 pulse cols)
    bp_cols = ["Date", "n"] + SYS_COLS + DIA_COLS
    pls_cols = ["Date", "n"] + PLS_COLS

    fig = new_page(pdf, "Daily statistics — blood pressure")
    fig.text(0.5, 0.875,
             "Systolic and diastolic: mean, min, max, AM/PM/Nt, 7-day rolling.",
             ha="center", fontsize=9, color="#555")
    add_table(fig, daily_stats[bp_cols], top=0.86, bottom=0.04,
              fontsize=8, col_widths=BP_WIDTHS, row_scale=1.15)
    pdf.savefig(fig); plt.close(fig); pages += 1

    fig = new_page(pdf, "Daily statistics — pulse")
    fig.text(0.5, 0.875,
             "Pulse: mean, min, max, AM/PM/Nt, 7-day rolling.",
             ha="center", fontsize=9, color="#555")
    add_table(fig, daily_stats[pls_cols], top=0.86, bottom=0.04,
              fontsize=9, col_widths=PLS_WIDTHS, row_scale=1.15)
    pdf.savefig(fig); plt.close(fig); pages += 1

print(f"wrote {out.name} ({out.stat().st_size // 1024} KB, {pages} pages)")
