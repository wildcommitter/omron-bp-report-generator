#!/usr/bin/env python3
"""Compose report.pdf from analysis artefacts using matplotlib PdfPages."""
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
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

SYS_COLS = ["Sys", "S−", "S+", "S 7d"]
DIA_COLS = ["Dia", "D−", "D+", "D 7d"]
PLS_COLS = ["Pls", "P−", "P+", "P 7d"]
BP_WIDTHS = [0.08, 0.04] + [0.11] * 8      # Date, n, 8 sys/dia cols
PLS_WIDTHS = [0.12, 0.06] + [0.205] * 4    # Date, n, 4 pulse cols

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
    # Cover (portrait) — clinical summary tailored for cardiology review
    cs_df = pd.read_csv(HERE / "clinical_summary.csv")
    cs = dict(zip(cs_df["key"], cs_df["value"]))
    stage_df = pd.read_csv(HERE / "stage_counts.csv")
    hourly_csv = pd.read_csv(HERE / "hourly_stats.csv").set_index("hour")

    def _surge(m):
        pre = hourly_csv.loc[hourly_csv.index < 6, f"{m}_mean"]
        morn = hourly_csv.loc[(hourly_csv.index >= 6) & (hourly_csv.index <= 10),
                              f"{m}_mean"]
        if pre.empty or morn.empty:
            return "—"
        return f"+{morn.max() - pre.min():.1f}"

    days_total = int(cs["days_total"])
    days_s2 = int(cs["days_stage2"])
    days_clean = int(cs["days_all_clean"])
    esh_above = int(cs["esh_above_n"])
    esh_pct = float(cs["esh_above_pct"])

    fig = new_page(pdf, "Blood pressure & pulse report", size=PORTRAIT)
    fig.text(0.5, 0.875, "Source: input.csv (OMRON Complete export)",
             ha="center", fontsize=10, style="italic", color="#666")

    LMARGIN = 0.08
    def _head(y, text):
        fig.text(LMARGIN, y, text, fontsize=11, fontweight="bold",
                 color="#1f3a5f")
    def _line(y, text):
        fig.text(LMARGIN + 0.03, y, text, fontsize=9.5, family="monospace",
                 color="#222")

    dense_n = int(cs.get("dense_weeks_n", 0))
    has_dense = dense_n > 0
    weeks_total = int(cs.get("weeks_total", 0))

    y = 0.84
    _head(y, "VITALS OVERVIEW")
    _line(y - 0.025, f"Systolic    {df['sys'].mean():>6.1f} mmHg     "
                    f"range {df['sys'].min()}–{df['sys'].max()}")
    _line(y - 0.045, f"Diastolic   {df['dia'].mean():>6.1f} mmHg     "
                    f"range {df['dia'].min()}–{df['dia'].max()}")
    _line(y - 0.065, f"Pulse       {df['pulse'].mean():>6.1f} bpm      "
                    f"range {df['pulse'].min()}–{df['pulse'].max()}")

    y = 0.745
    _head(y, f"TRAJECTORY ACROSS {weeks_total} WEEK"
             f"{'S' if weeks_total != 1 else ''}")
    _line(y - 0.025, f"Phenotype mix   {cs.get('phenotype_summary', '—')}")
    _line(y - 0.045,
          f"Longest in-target streak    {cs.get('window_streak_in', '—')} "
          f"days   (out-of-target {cs.get('window_streak_out', '—')})")

    y = 0.675
    _head(y, "VARIABILITY (ARV on daily means, PP per reading)")
    _line(y - 0.025,
          f"ARV    sys {cs.get('window_arv_s','—')}   "
          f"dia {cs.get('window_arv_d','—')}   "
          f"pulse {cs.get('window_arv_p','—')}    mmHg / bpm")
    _line(y - 0.045,
          f"Pulse pressure   mean {cs.get('window_pp_mean','—')}   "
          f"max {cs.get('window_pp_max','—')}    mmHg")

    if has_dense:
        y = 0.60
        _head(y, f"DAY VS NIGHT — ESH 07–23h / 23–07h  ({dense_n}/{weeks_total} weeks dense)")
        _line(y - 0.025,
              f"Daytime      {cs['day_sys_mean']}/{cs['day_dia_mean']} mmHg   "
              f"(n={cs['day_n']})")
        _line(y - 0.045,
              f"Nighttime    {cs['night_sys_mean']}/{cs['night_dia_mean']} mmHg   "
              f"(n={cs['night_n']})")
        _line(y - 0.065,
              f"Nocturnal dip   sys {cs['dip_sys_pct']}%   "
              f"dia {cs['dip_dia_pct']}%   → {cs['dip_pattern']}")

        y = 0.51
        _head(y, "MORNING SURGE (peak 06–10h − trough 00–06h)")
        _line(y - 0.025,
              f"Sys {_surge('sys')}   Dia {_surge('dia')}   Pulse {_surge('pulse')}")
        _line(y - 0.045,
              "Sys surge ≥20 mmHg is flagged as excessive in CV literature.")
        dist_y = 0.44
    else:
        dist_y = 0.60

    y = dist_y
    _head(y, "READING DISTRIBUTION (ACC/AHA per individual reading)")
    labels = {"Normal": "<120/80", "Elevated": "120–129",
              "Stage 1": "130–139 or 80–89", "Stage 2": "≥140 or ≥90",
              "Crisis": "≥180 or ≥120"}
    for i, row in stage_df.iterrows():
        s = row["stage"]
        bracket = f"({labels[s]})"
        _line(y - 0.025 - i * 0.020,
              f"{s:<10}  {bracket:<22} {int(row['count']):>4}  "
              f"({row['pct']:>5.1f}%)")

    y = dist_y - 0.16
    _head(y, "TIME IN RANGE")
    _line(y - 0.025,
          f"Above ESH home threshold (≥135/85):  {esh_above} readings "
          f"({esh_pct:.1f}%)")
    _line(y - 0.045,
          f"Days with ≥1 Stage-2 reading:  {days_s2}/{days_total} "
          f"({days_s2/days_total*100:.0f}%)")
    _line(y - 0.065,
          f"All-clean days (<135/85 throughout):  {days_clean}/{days_total} "
          f"({days_clean/days_total*100:.0f}%)")

    y = dist_y - 0.27
    _head(y, "HIGHEST SINGLE READING")
    _line(y - 0.025,
          f"{cs['max_sys']}/{cs['max_dia']} mmHg, pulse {cs['max_pulse']} bpm "
          f"on {cs['max_ts']}")

    fig.text(0.5, 0.05,
             f"Generated {datetime.now():%Y-%m-%d %H:%M}  ·  "
             "Not medical advice; for clinical interpretation by a "
             "qualified clinician.",
             ha="center", fontsize=8.5, color="#888")
    pdf.savefig(fig); plt.close(fig); pages += 1

    # Time in range — daily stacked breakdown, repeated by month (top row
    # of panels) and by ISO week (bottom row of panels).
    if (HERE / "time_in_range.png").exists():
        fig = new_page(pdf, "Time in range — daily stage distribution")
        fig.text(0.5, 0.875,
                 "Each bar = one day's readings stacked by ACC/AHA stage. "
                 "Top row: per calendar month. Bottom row: per ISO week.",
                 ha="center", fontsize=9, color="#555")
        add_image(fig, HERE / "time_in_range.png", top=0.86, bottom=0.04)
        pdf.savefig(fig); plt.close(fig); pages += 1

    # Weekly clinical digest — one row per ISO week, all the cover-page
    # headlines reproduced for each week so trajectories are visible.
    wc_path = HERE / "weekly_clinical_summary.csv"
    if wc_path.exists():
        wc = pd.read_csv(wc_path)
        wc["week_start"] = pd.to_datetime(wc["week_start"])

        def _delta(v):
            if pd.isna(v):
                return "—"
            return f"{v:+.1f}"

        def _val(v, fmt="{:.1f}", suffix=""):
            return "—" if pd.isna(v) else fmt.format(v) + suffix

        def _phen_short(row):
            primary = row.get("phenotype_primary") or ""
            secondary = row.get("phenotype_secondary") or ""
            tags = [primary] + (secondary.split(";") if secondary else [])
            return "+".join(t for t in tags if t)

        rows = []
        for _, r in wc.iterrows():
            is_dense = bool(r.get("is_dense", True))
            dip_cell = (
                "—" if not is_dense else
                _val(r["dip_sys_pct"], suffix="%") +
                    (f"  (n_n={int(r['night_n'])})"
                     if not pd.isna(r["night_n"]) and r["night_n"] < 5 else "")
            )
            surge_cell = (
                "—" if not is_dense else
                (_val(r["surge_sys"], fmt="+{:.1f}")
                 if not pd.isna(r["surge_sys"]) else "—")
            )
            rows.append([
                r["week_start"].strftime("%d %b"),
                int(r["n"]),
                _val(r["sys_mean"]),
                _val(r["dia_mean"]),
                _val(r["pulse_mean"]),
                _delta(r["d_sys"]),
                _delta(r["d_dia"]),
                _val(r.get("arv_s")),
                _val(r.get("pp_mean")),
                dip_cell,
                surge_cell,
                _val(r["esh_above_pct"], suffix="%"),
                f"{int(r['days_stage2'])}/{int(r['days_in_week'])}",
                _phen_short(r),
            ])
        wc_table = pd.DataFrame(rows, columns=[
            "Week of", "n", "Sys", "Dia", "HR",
            "Δ Sys", "Δ Dia",
            "ARV(s)", "PP",
            "Dip % sys", "Surge sys",
            "ESH ≥135/85", "S2 days", "Phenotype",
        ])

        fig = new_page(pdf, "Weekly clinical digest")
        fig.text(0.5, 0.875,
                 "Cover-page metrics + new tier-1 numbers (ARV, PP, "
                 "phenotype), per ISO week. Dip/surge are '—' for "
                 "sparse weeks (≤2 readings/day); dense-week night-n "
                 "is flagged when <5.",
                 ha="center", fontsize=8.5, color="#555")
        add_table(fig, wc_table, top=0.85, bottom=0.10,
                  fontsize=8, row_scale=1.4,
                  col_widths=[0.07, 0.035, 0.05, 0.05, 0.05,
                              0.055, 0.055,
                              0.05, 0.045,
                              0.10, 0.07,
                              0.075, 0.055, 0.16])
        fig.text(0.5, 0.07,
                 "Reference thresholds: ESH home BP ≥135/85 mmHg · "
                 "ACC/AHA Stage 2 ≥140/90 · Normal dipper ≥10% · "
                 "Excessive surge ≥20 mmHg.",
                 ha="center", fontsize=8.5, color="#555", style="italic")
        pdf.savefig(fig); plt.close(fig); pages += 1

    # Trend over time (landscape)
    fig = new_page(pdf, "Trend over time")
    fig.text(0.5, 0.875,
             "Individual readings, daily mean, 7-day rolling average. "
             "Top-2 spikes per metric annotated.",
             ha="center", fontsize=9, color="#555")
    add_image(fig, HERE / "vitals.png", top=0.85, bottom=0.04)
    pdf.savefig(fig); plt.close(fig); pages += 1

    # Weekly trend (landscape) — chart-form view of the per-week period
    # averages.  Tabular form was dropped as it duplicated this chart.
    fig = new_page(pdf, "Weekly trend by 8-hour period")
    add_image(fig, HERE / "periods_weekly.png", top=0.88, bottom=0.06)
    pdf.savefig(fig); plt.close(fig); pages += 1

    # Diurnal (24-hour) pattern, faceted by ISO week.  Each row is one
    # metric (sys/dia/pulse); each column is one week's hour-of-day curve.
    if (HERE / "diurnal.png").exists():
        fig = new_page(pdf, "Diurnal pattern by hour of day")
        fig.text(0.5, 0.875,
                 "Rows: Sys / Dia / Pulse.  Columns: one ISO week each. "
                 "Lines are hourly means; faint dots are individual readings.",
                 ha="center", fontsize=9, color="#555")
        add_image(fig, HERE / "diurnal.png", top=0.86, bottom=0.04)
        pdf.savefig(fig); plt.close(fig); pages += 1

    # === Per-week mini reports — one page per ISO week ===
    def _stage(s, d):
        if s >= 180 or d >= 120: return "Crisis"
        if s >= 140 or d >= 90:  return "Stage 2"
        if s >= 130 or d >= 80:  return "Stage 1"
        if s >= 120:             return "Elevated"
        return "Normal"
    _STAGE_COLORS = {"Normal":"#2ca02c", "Elevated":"#fdd835",
                     "Stage 1":"#ff7f0e", "Stage 2":"#d62728",
                     "Crisis":"#7b1fa2"}
    _LIGHT_TXT_STAGES = {"Stage 1", "Stage 2", "Crisis"}

    def _render_weekly_page(pdf_, df_w, wk, wc_row, wc_prev):
        n_r = len(df_w)
        n_d = df_w["ts"].dt.date.nunique()
        fig_ = plt.figure(figsize=(11, 8.5))
        fig_.suptitle(f"Weekly mini report — Week of {wk:%d %b %Y}",
                      fontsize=16, fontweight="bold", y=0.97)
        fig_.text(0.5, 0.935,
                  f"{df_w['ts'].min():%d %b} → {df_w['ts'].max():%d %b %Y}  ·  "
                  f"{n_r} readings  ·  {n_d} days",
                  ha="center", fontsize=10, color="#555")

        # ----- left column (text) -----
        L = 0.04
        def _h(y, t):
            fig_.text(L, y, t, fontsize=11, fontweight="bold", color="#1f3a5f")
        def _l(y, t, color="#222"):
            fig_.text(L + 0.012, y, t, fontsize=9,
                      family="monospace", color=color)

        y = 0.87
        _h(y, "CLINICAL METRICS")
        _l(y - 0.025,
           f"Sys     {df_w['sys'].mean():>6.1f} mmHg")
        _l(y - 0.045,
           f"Dia     {df_w['dia'].mean():>6.1f} mmHg")
        _l(y - 0.065,
           f"Pulse   {df_w['pulse'].mean():>6.1f} bpm")

        y = 0.77
        _h(y, "VARIANCE")
        for i, m in enumerate(("sys", "dia", "pulse")):
            sd = df_w[m].std()
            mean = df_w[m].mean()
            cv = sd / mean * 100 if mean else 0
            lo, hi = int(df_w[m].min()), int(df_w[m].max())
            _l(y - 0.025 - i * 0.020,
               f"{m.capitalize():6}  SD {sd:>4.1f}  CV {cv:>4.1f}%  "
               f"range {lo}–{hi}")

        y = 0.65
        _h(y, "PATTERN")
        dip_v = wc_row["dip_sys_pct"]
        surge_v = wc_row["surge_sys"]
        dip_str = (f"{dip_v:>5.1f}%" if pd.notna(dip_v) else "  —  ")
        surge_str = (f"+{surge_v:>4.1f}" if pd.notna(surge_v) else "  —  ")
        _l(y - 0.025, f"Nocturnal dip sys   {dip_str}")
        _l(y - 0.045, f"Morning surge sys   {surge_str}")
        _l(y - 0.065,
           f"ESH ≥135/85         {int(wc_row['esh_above_n'])}/{n_r}  "
           f"({wc_row['esh_above_pct']:.1f}%)")
        _l(y - 0.085,
           f"Stage-2 days        {int(wc_row['days_stage2'])}/"
           f"{int(wc_row['days_in_week'])}")

        y = 0.50
        _h(y, "Δ vs PRIOR WEEK")
        if wc_prev is None:
            _l(y - 0.025, "(first week — no prior to compare)",
               color="#888")
        else:
            for i, m in enumerate(("sys", "dia", "pulse")):
                d = wc_row[f"{m}_mean"] - wc_prev[f"{m}_mean"]
                arrow = "↓" if d < -0.05 else ("↑" if d > 0.05 else "→")
                color = ("#2e7d32" if d < -0.05
                         else "#c62828" if d > 0.05
                         else "#888")
                _l(y - 0.025 - i * 0.020,
                   f"{m.capitalize():6}  {arrow}  {d:+5.1f}", color=color)

        # ----- right column (3-panel trend) -----
        daily_w = (df_w.set_index("ts").resample("D")
                    .mean(numeric_only=True).dropna())
        trend_specs = [
            ("sys",   "Sys (mmHg)",   "#1f77b4",
             [120, 130, 140], (90, 170)),
            ("dia",   "Dia (mmHg)",   "#9467bd",
             [80, 90],        (55, 100)),
            ("pulse", "Pulse (bpm)",  "#e377c2",
             [100],           (60, 140)),
        ]
        for i, (m, lab, c, thrs, ylim) in enumerate(trend_specs):
            ax = fig_.add_axes([0.40, 0.72 - i * 0.21, 0.55, 0.18])
            ax.scatter(df_w["ts"], df_w[m], s=14, color=c, alpha=0.35)
            ax.plot(daily_w.index, daily_w[m], "o-",
                    color=c, lw=2, ms=5)
            for thr in thrs:
                ax.axhline(thr, color="#888", lw=0.6, ls="--", alpha=0.5)
            ax.set_ylabel(lab, fontweight="bold", fontsize=8.5)
            ax.set_ylim(*ylim)
            ax.tick_params(axis="y", labelsize=7)
            ax.grid(True, alpha=0.25)
            if i < 2:
                ax.set_xticklabels([])
            else:
                ax.xaxis.set_major_locator(mdates.DayLocator())
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
                plt.setp(ax.get_xticklabels(),
                         rotation=30, ha="right", fontsize=7)

        # ----- bottom: time-in-range bar -----
        ax_tir = fig_.add_axes([0.40, 0.10, 0.55, 0.085])
        stages_w = [_stage(s, d) for s, d in zip(df_w["sys"], df_w["dia"])]
        left = 0
        for label in ["Normal", "Elevated", "Stage 1", "Stage 2", "Crisis"]:
            cnt = stages_w.count(label)
            pct = cnt / n_r * 100 if n_r else 0
            if pct > 0:
                ax_tir.barh(0, pct, left=left,
                            color=_STAGE_COLORS[label],
                            edgecolor="white", lw=2)
                if pct >= 9:
                    ax_tir.text(left + pct / 2, 0,
                                f"{label}\n{pct:.0f}%",
                                ha="center", va="center",
                                fontsize=7.5, fontweight="bold",
                                color=("white" if label in _LIGHT_TXT_STAGES
                                       else "#222"))
                left += pct
        ax_tir.set_xlim(0, 100)
        ax_tir.set_ylim(-0.5, 0.5)
        ax_tir.set_yticks([])
        ax_tir.set_xlabel("% of readings", fontsize=8)
        ax_tir.set_title("Time in range (ACC/AHA)",
                         fontweight="bold", fontsize=9.5, pad=4)

        pdf_.savefig(fig_)
        plt.close(fig_)

    # Window-wide mean+2SD ceiling for per-day outlier flagging
    OUTLIER_HI = {m: float(df[m].mean() + 2 * df[m].std())
                  for m in ("sys", "dia", "pulse")}

    def _plot_daily_markers(ax, series, color, ms=6):
        """Line + per-point markers: weekday=circle, weekend=square,
        red ring when value exceeds the window-wide mean+2SD ceiling."""
        m_key = series.name
        ax.plot(series.index, series.values, color=color, lw=2, zorder=3)
        for d, v in series.items():
            if pd.isna(v):
                continue
            ts = pd.Timestamp(d)
            weekend = ts.weekday() >= 5
            outlier = v > OUTLIER_HI.get(m_key, float("inf"))
            ax.plot(d, v,
                    marker=("s" if weekend else "o"),
                    color=color, ms=ms,
                    markeredgecolor=("#c62828" if outlier else "white"),
                    markeredgewidth=(1.8 if outlier else 0.6),
                    zorder=4)

    # Phenotype chip color: green = controlled, amber = borderline/labile/climbing,
    # red = uncontrolled/crisis/isolated-systolic.
    PHENOTYPE_COLORS = {
        "Controlled":        "#2e7d32",
        "Borderline":        "#f9a825",
        "Labile":            "#f9a825",
        "Climbing":          "#f9a825",
        "Uncontrolled":      "#c62828",
        "Crisis":            "#7b1fa2",
        "Isolated-systolic": "#c62828",
    }

    def _phenotype_chip(fig_, x, y, primary, secondary):
        color = PHENOTYPE_COLORS.get(primary, "#555")
        label = primary if not secondary else f"{primary} · {secondary.replace(';', ' · ')}"
        fig_.text(x, y, label, ha="right", va="center",
                  fontsize=10.5, fontweight="bold", color="white",
                  bbox=dict(boxstyle="round,pad=0.5", facecolor=color,
                            edgecolor=color))

    def _render_weekly_page_sparse(pdf_, df_w, wk, wc_row, wc_prev):
        n_r = len(df_w)
        n_d = df_w["ts"].dt.date.nunique()
        fig_ = plt.figure(figsize=(11, 8.5))
        fig_.suptitle(f"Weekly mini report — Week of {wk:%d %b %Y}",
                      fontsize=16, fontweight="bold", y=0.97, x=0.30, ha="center")
        fig_.text(0.30, 0.935,
                  f"{df_w['ts'].min():%d %b} → {df_w['ts'].max():%d %b %Y}  ·  "
                  f"{n_r} readings  ·  {n_d} days  ·  "
                  f"~{wc_row['readings_per_day_median']:.0f}/day",
                  ha="center", fontsize=10, color="#555")
        _phenotype_chip(fig_, 0.96, 0.955,
                        wc_row["phenotype_primary"],
                        wc_row.get("phenotype_secondary") or "")

        # ----- left column (text) -----
        L = 0.04
        def _h(y, t):
            fig_.text(L, y, t, fontsize=11, fontweight="bold", color="#1f3a5f")
        def _l(y, t, color="#222"):
            fig_.text(L + 0.012, y, t, fontsize=9,
                      family="monospace", color=color)

        y = 0.87
        _h(y, "CLINICAL METRICS")
        _l(y - 0.025, f"Sys     {df_w['sys'].mean():>6.1f} mmHg")
        _l(y - 0.045, f"Dia     {df_w['dia'].mean():>6.1f} mmHg")
        _l(y - 0.065, f"Pulse   {df_w['pulse'].mean():>6.1f} bpm")
        _l(y - 0.085, f"PP      {wc_row['pp_mean']:>6.1f} mmHg "
                      f"(max {int(wc_row['pp_max'])})")

        y = 0.74
        _h(y, "Δ vs PRIOR WEEK")
        if wc_prev is None:
            _l(y - 0.025, "(first week — no prior to compare)", color="#888")
        else:
            for i, m in enumerate(("sys", "dia", "pulse")):
                d = wc_row[f"{m}_mean"] - wc_prev[f"{m}_mean"]
                arrow = "↓" if d < -0.05 else ("↑" if d > 0.05 else "→")
                # Down arrow on BP/HR = improvement; up = worsening.
                color = ("#2e7d32" if d < -0.05
                         else "#c62828" if d > 0.05
                         else "#888")
                _l(y - 0.025 - i * 0.020,
                   f"{m.capitalize():6}  {arrow}  {d:+5.1f}", color=color)

        y = 0.62
        _h(y, "VARIABILITY")
        def _arvline(label, m, arv_key):
            sd = df_w[m].std()
            mean = df_w[m].mean()
            cv = sd / mean * 100 if mean else 0
            arv = wc_row.get(arv_key)
            arv_str = f"{arv:>4.1f}" if pd.notna(arv) else "  —"
            return (f"{label:6}  ARV {arv_str}  SD {sd:>4.1f}  CV {cv:>4.1f}%")
        for i, (label, m, arv_key) in enumerate([
            ("Sys",   "sys",   "arv_s"),
            ("Dia",   "dia",   "arv_d"),
            ("Pulse", "pulse", "arv_p"),
        ]):
            _l(y - 0.025 - i * 0.020, _arvline(label, m, arv_key))

        y = 0.49
        _h(y, "CONTROL")
        _l(y - 0.025,
           f"ESH ≥135/85    {int(wc_row['esh_above_n'])}/{n_r}  "
           f"({wc_row['esh_above_pct']:.1f}%)")
        _l(y - 0.045,
           f"In-target streak    {int(wc_row['streak_in_target'])} days")
        _l(y - 0.065,
           f"Out-of-target streak {int(wc_row['streak_out_of_target'])} days")
        _l(y - 0.085,
           f"Stage-2 days       {int(wc_row['days_stage2'])}/"
           f"{int(wc_row['days_in_week'])}")

        y = 0.355
        _h(y, "TREND (slope ± 95% CI)")
        def _slope_line(label, key, ci_key, unit):
            s = wc_row.get(key)
            ci = wc_row.get(ci_key)
            if pd.isna(s) or pd.isna(ci):
                return f"{label:6}  —"
            arrow = "↑" if (s - ci) > 0 else ("↓" if (s + ci) < 0 else "→")
            color = ("#c62828" if arrow == "↑"
                     else "#2e7d32" if arrow == "↓"
                     else "#888")
            return (f"{label:6}  {arrow}  {s:+.2f} ± {ci:.2f}  {unit}/day"), color
        for i, (label, k, ck, u) in enumerate([
            ("Sys",   "slope_s", "slope_s_ci", "mmHg"),
            ("Dia",   "slope_d", "slope_d_ci", "mmHg"),
            ("Pulse", "slope_p", "slope_p_ci", "bpm"),
        ]):
            res = _slope_line(label, k, ck, u)
            if isinstance(res, tuple):
                _l(y - 0.025 - i * 0.020, res[0], color=res[1])
            else:
                _l(y - 0.025 - i * 0.020, res, color="#888")

        y = 0.255
        _h(y, "PERFUSION & WORKLOAD")
        map_v = wc_row.get("map_mean")
        r_v = wc_row.get("coupling_r")
        rpp_v = wc_row.get("rpp_mean")
        map_str = f"{map_v:.1f}" if pd.notna(map_v) else "—"
        r_str = (f"{r_v:+.2f}" if pd.notna(r_v) else "—")
        rpp_str = f"{rpp_v:.1f}" if pd.notna(rpp_v) else "—"
        _l(y - 0.025,
           f"MAP   {map_str} mmHg     RPP   {rpp_str}k")
        _l(y - 0.045,
           f"sys–HR r   {r_str}")
        ttt = wc_row.get("time_to_target_days")
        if pd.notna(ttt):
            _l(y - 0.065,
               f"→ projected to reach 135 in ~{int(ttt)} days at current pace",
               color="#2e7d32")

        # ----- right column (3-panel trend: sys+dia / HR / PP) -----
        daily_w = (df_w.set_index("ts").resample("D")
                    .mean(numeric_only=True).dropna(subset=["sys"]))

        # Panel 1: sys + dia overlay
        ax1 = fig_.add_axes([0.40, 0.72, 0.55, 0.18])
        ax1.scatter(df_w["ts"], df_w["sys"], s=14, color="#1f77b4", alpha=0.35)
        ax1.scatter(df_w["ts"], df_w["dia"], s=14, color="#9467bd", alpha=0.35)
        sys_series = daily_w["sys"].rename("sys")
        dia_series = daily_w["dia"].rename("dia")
        _plot_daily_markers(ax1, sys_series, "#1f77b4")
        _plot_daily_markers(ax1, dia_series, "#9467bd")
        ax1.plot([], [], "o", color="#1f77b4", label="Sys")
        ax1.plot([], [], "o", color="#9467bd", label="Dia")
        for thr in (120, 130, 140):
            ax1.axhline(thr, color="#888", lw=0.6, ls="--", alpha=0.5)
        for thr in (80, 90):
            ax1.axhline(thr, color="#888", lw=0.6, ls=":", alpha=0.5)
        ax1.set_ylabel("BP (mmHg)", fontweight="bold", fontsize=8.5)
        ax1.set_ylim(50, 170)
        ax1.tick_params(axis="y", labelsize=7)
        ax1.grid(True, alpha=0.25)
        ax1.legend(loc="upper right", fontsize=7, framealpha=0.9, ncol=2)
        ax1.set_xticklabels([])

        # Panel 2: HR with 60/80/100 bands
        ax2 = fig_.add_axes([0.40, 0.51, 0.55, 0.18])
        ax2.axhspan(60, 80, color="#2ca02c", alpha=0.08)
        ax2.axhspan(80, 100, color="#fdd835", alpha=0.12)
        ax2.axhspan(100, 140, color="#d62728", alpha=0.12)
        ax2.scatter(df_w["ts"], df_w["pulse"], s=14, color="#e377c2", alpha=0.35)
        _plot_daily_markers(ax2, daily_w["pulse"].rename("pulse"), "#e377c2")
        for thr, lab in [(60, "60"), (80, "80"), (100, "100")]:
            ax2.axhline(thr, color="#888", lw=0.6, ls="--", alpha=0.5)
            ax2.text(1.0, thr, f" {lab}", transform=ax2.get_yaxis_transform(),
                     fontsize=7, color="#555", va="center")
        ax2.set_ylabel("Pulse (bpm)", fontweight="bold", fontsize=8.5)
        ax2.set_ylim(50, 140)
        ax2.tick_params(axis="y", labelsize=7)
        ax2.grid(True, alpha=0.25)
        ax2.set_xticklabels([])

        # Panel 3: PP daily bar
        ax3 = fig_.add_axes([0.40, 0.30, 0.55, 0.18])
        daily_pp = daily_w["sys"] - daily_w["dia"]
        ax3.bar(daily_pp.index, daily_pp.values, width=0.7,
                color="#8c8ad8", edgecolor="white")
        ax3.axhline(40, color="#888", lw=0.6, ls="--", alpha=0.5)
        ax3.axhline(60, color="#c62828", lw=0.8, ls="--", alpha=0.6)
        ax3.text(1.0, 60, " wide (≥60)", transform=ax3.get_yaxis_transform(),
                 fontsize=7, color="#c62828", va="center")
        ax3.set_ylabel("PP (mmHg)", fontweight="bold", fontsize=8.5)
        ax3.set_ylim(0, max(80, daily_pp.max() + 5) if not daily_pp.empty else 80)
        ax3.tick_params(axis="y", labelsize=7)
        ax3.grid(True, alpha=0.25, axis="y")
        ax3.xaxis.set_major_locator(mdates.DayLocator())
        ax3.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        plt.setp(ax3.get_xticklabels(), rotation=30, ha="right", fontsize=7)

        fig_.text(0.95, 0.225,
                  "○ weekday   ◻ weekend   red ring = > window mean+2SD",
                  ha="right", fontsize=7.5, color="#555", style="italic")

        # ----- bottom: time-in-range bar -----
        ax_tir = fig_.add_axes([0.40, 0.10, 0.55, 0.085])
        stages_w = [_stage(s, d) for s, d in zip(df_w["sys"], df_w["dia"])]
        left = 0
        for label in ["Normal", "Elevated", "Stage 1", "Stage 2", "Crisis"]:
            cnt = stages_w.count(label)
            pct = cnt / n_r * 100 if n_r else 0
            if pct > 0:
                ax_tir.barh(0, pct, left=left,
                            color=_STAGE_COLORS[label],
                            edgecolor="white", lw=2)
                if pct >= 9:
                    ax_tir.text(left + pct / 2, 0, f"{label}\n{pct:.0f}%",
                                ha="center", va="center",
                                fontsize=7.5, fontweight="bold",
                                color=("white" if label in _LIGHT_TXT_STAGES
                                       else "#222"))
                left += pct
        ax_tir.set_xlim(0, 100)
        ax_tir.set_ylim(-0.5, 0.5)
        ax_tir.set_yticks([])
        ax_tir.set_xlabel("% of readings", fontsize=8)
        ax_tir.set_title("Time in range (ACC/AHA)",
                         fontweight="bold", fontsize=9.5, pad=4)

        pdf_.savefig(fig_)
        plt.close(fig_)

    df_with_week = df.assign(
        week_start=df["ts"].dt.to_period("W-SUN")
                   .apply(lambda p: p.start_time))
    wc_full = pd.read_csv(HERE / "weekly_clinical_summary.csv")
    wc_full["week_start"] = pd.to_datetime(wc_full["week_start"])
    for i, (wk, df_wk) in enumerate(df_with_week.groupby("week_start")):
        wc_row = wc_full.iloc[i]
        wc_prev = wc_full.iloc[i - 1] if i > 0 else None
        if bool(wc_row.get("is_dense", True)):
            _render_weekly_page(pdf, df_wk, wk, wc_row, wc_prev)
        else:
            _render_weekly_page_sparse(pdf, df_wk, wk, wc_row, wc_prev)
        pages += 1

    # Daily statistics — raw-numbers appendix, at the end of the report so
    # the clinical narrative on the earlier pages isn't interrupted.
    bp_cols = ["Date", "n"] + SYS_COLS + DIA_COLS
    pls_cols = ["Date", "n"] + PLS_COLS

    fig = new_page(pdf, "Daily statistics — blood pressure")
    fig.text(0.5, 0.875,
             "Systolic and diastolic: mean, min, max, 7-day rolling.",
             ha="center", fontsize=9, color="#555")
    add_table(fig, daily_stats[bp_cols], top=0.86, bottom=0.04,
              fontsize=8, col_widths=BP_WIDTHS, row_scale=1.15)
    pdf.savefig(fig); plt.close(fig); pages += 1

    fig = new_page(pdf, "Daily statistics — pulse")
    fig.text(0.5, 0.875,
             "Pulse: mean, min, max, 7-day rolling.",
             ha="center", fontsize=9, color="#555")
    add_table(fig, daily_stats[pls_cols], top=0.86, bottom=0.04,
              fontsize=9, col_widths=PLS_WIDTHS, row_scale=1.15)
    pdf.savefig(fig); plt.close(fig); pages += 1

print(f"wrote {out.name} ({out.stat().st_size // 1024} KB, {pages} pages)")
