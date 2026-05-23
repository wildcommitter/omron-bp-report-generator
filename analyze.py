#!/usr/bin/env python3
"""Plot systolic, diastolic and pulse from input.csv (OMRON Spanish export)."""
import math

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import linregress

from bp_utils import load_omron_csv


def autoscale(values, pad=5, step=10):
    """Round (min-pad, max+pad) outwards to multiples of step."""
    lo = math.floor((min(values) - pad) / step) * step
    hi = math.ceil((max(values) + pad) / step) * step
    return lo, hi

df = load_omron_csv("input.csv")
df["pp"] = df["sys"] - df["dia"]   # pulse pressure (arterial-stiffness proxy)

# 8-hour periods starting at 07:00: morning 07–15, evening 15–23, night 23–07
def period(h):
    if 7 <= h < 15:  return "1. morning (07–15)"
    if 15 <= h < 23: return "2. evening (15–23)"
    return "3. night (23–07)"

df_p = df.assign(period=df["ts"].dt.hour.map(period))

daily_stats = df.set_index("ts").resample("D").agg(
    readings=("sys", "count"),
    sys_mean=("sys", "mean"), sys_min=("sys", "min"), sys_max=("sys", "max"),
    dia_mean=("dia", "mean"), dia_min=("dia", "min"), dia_max=("dia", "max"),
    pulse_mean=("pulse", "mean"), pulse_min=("pulse", "min"),
    pulse_max=("pulse", "max"),
).dropna(subset=["sys_mean"])

PERIOD_SHORT = {"1. morning (07–15)": "morn",
                "2. evening (15–23)": "eve",
                "3. night (23–07)":   "night"}
period_daily = (df_p.set_index("ts")
                .groupby([pd.Grouper(freq="D"), "period"])[["sys", "dia", "pulse"]]
                .mean().unstack())
period_daily.columns = [f"{m}_{PERIOD_SHORT[p]}" for m, p in period_daily.columns]
daily_stats = daily_stats.join(period_daily)

for c in ("sys_mean", "dia_mean", "pulse_mean"):
    daily_stats[c.replace("_mean", "_7d_avg")] = (
        daily_stats[c].rolling("7D", min_periods=1).mean()
    )

# Group columns by metric: each metric gets mean/min/max/AM/PM/Nt/7d together
daily_stats = daily_stats[[
    "readings",
    "sys_mean", "sys_min", "sys_max",
    "sys_morn", "sys_eve", "sys_night", "sys_7d_avg",
    "dia_mean", "dia_min", "dia_max",
    "dia_morn", "dia_eve", "dia_night", "dia_7d_avg",
    "pulse_mean", "pulse_min", "pulse_max",
    "pulse_morn", "pulse_eve", "pulse_night", "pulse_7d_avg",
]]
daily_stats = daily_stats.round(1)
daily_stats.index.name = "date"
daily_stats.to_csv("daily_stats.csv", date_format="%Y-%m-%d")

daily = daily_stats[["sys_mean", "dia_mean", "pulse_mean"]].rename(
    columns={"sys_mean": "sys", "dia_mean": "dia", "pulse_mean": "pulse"})
rolling = daily_stats[["sys_7d_avg", "dia_7d_avg", "pulse_7d_avg"]].rename(
    columns={"sys_7d_avg": "sys", "dia_7d_avg": "dia", "pulse_7d_avg": "pulse"})
period_stats = df_p.groupby("period").agg(
    readings=("sys", "count"),
    sys_mean=("sys", "mean"), sys_min=("sys", "min"), sys_max=("sys", "max"),
    dia_mean=("dia", "mean"), dia_min=("dia", "min"), dia_max=("dia", "max"),
    pulse_mean=("pulse", "mean"), pulse_min=("pulse", "min"),
    pulse_max=("pulse", "max"),
).round(1)
period_stats.to_csv("period_stats.csv")
print("\nAverages by 8h period (starting 07:00):")
print(period_stats.to_string())

fig2, (ax_bp, ax_pul) = plt.subplots(1, 2, figsize=(11, 5),
                                     gridspec_kw={"width_ratios": [2, 1]})
periods_idx = period_stats.index.tolist()
x = range(len(periods_idx))
bar_w = 0.38

def err(series_mean, series_min, series_max):
    return [series_mean - series_min, series_max - series_mean]

ax_bp.bar([i - bar_w/2 for i in x], period_stats["sys_mean"], bar_w,
          yerr=err(period_stats["sys_mean"], period_stats["sys_min"],
                   period_stats["sys_max"]),
          capsize=4, color="#1f77b4", label="Systolic", alpha=0.85)
ax_bp.bar([i + bar_w/2 for i in x], period_stats["dia_mean"], bar_w,
          yerr=err(period_stats["dia_mean"], period_stats["dia_min"],
                   period_stats["dia_max"]),
          capsize=4, color="#9467bd", label="Diastolic", alpha=0.85)
for i, p in enumerate(periods_idx):
    ax_bp.text(i - bar_w/2, period_stats["sys_mean"].iloc[i] + 1,
               f"{period_stats['sys_mean'].iloc[i]:.1f}",
               ha="center", fontsize=9, fontweight="bold")
    ax_bp.text(i + bar_w/2, period_stats["dia_mean"].iloc[i] + 1,
               f"{period_stats['dia_mean'].iloc[i]:.1f}",
               ha="center", fontsize=9, fontweight="bold")
ax_bp.set_xticks(list(x))
ax_bp.set_xticklabels(periods_idx)
ax_bp.set_ylabel("mmHg", fontweight="bold")
ax_bp.set_title("Blood pressure by 8h period")
ax_bp.set_ylim(0, period_stats["sys_max"].max() * 1.1)
ax_bp.legend(loc="upper right")
ax_bp.axhline(120, color="#fdd835", lw=1, ls="--", alpha=0.6)
ax_bp.axhline(130, color="#ff7f0e", lw=1, ls="--", alpha=0.6)
ax_bp.axhline(140, color="#d62728", lw=1, ls="--", alpha=0.6)

ax_pul.bar(x, period_stats["pulse_mean"],
           yerr=err(period_stats["pulse_mean"], period_stats["pulse_min"],
                    period_stats["pulse_max"]),
           capsize=4, color="#e377c2", alpha=0.85)
for i, p in enumerate(periods_idx):
    ax_pul.text(i, period_stats["pulse_mean"].iloc[i] + 1,
                f"{period_stats['pulse_mean'].iloc[i]:.1f}",
                ha="center", fontsize=9, fontweight="bold")
ax_pul.set_xticks(list(x))
ax_pul.set_xticklabels(periods_idx)
ax_pul.set_ylabel("bpm", fontweight="bold")
ax_pul.set_title("Pulse by 8h period")
ax_pul.set_ylim(0, period_stats["pulse_max"].max() * 1.1)
ax_pul.axhline(100, color="#ff7f0e", lw=1, ls="--", alpha=0.6,
               label="Tachycardia (100)")
ax_pul.legend(loc="upper right")

fig2.suptitle("Averages by 8h period (whiskers = min–max range)",
              fontsize=13, fontweight="bold")
fig2.tight_layout(rect=[0, 0, 1, 0.94])
fig2.savefig("periods.png", dpi=150)

# Weekly breakdown by period
df_w = df_p.assign(
    week_start=df["ts"].dt.to_period("W-SUN").apply(lambda p: p.start_time)
)
weekly = df_w.groupby(["week_start", "period"]).agg(
    sys=("sys", "mean"), dia=("dia", "mean"), pulse=("pulse", "mean"),
    n=("sys", "count"),
).round(1)

# Week-over-week delta within each period
weekly_deltas = (weekly[["sys", "dia", "pulse"]]
                 .groupby(level="period").diff().round(1))
weekly_deltas.columns = ["d_sys", "d_dia", "d_pulse"]
weekly = weekly.join(weekly_deltas)
weekly.to_csv("weekly_period_stats.csv")

weeks = sorted(df_w["week_start"].unique())
week_labels = [pd.Timestamp(w).strftime("%d %b") for w in weeks]
period_order = sorted(df_w["period"].unique())
period_colors = {"1. morning (07–15)": "#f4a261",
                 "2. evening (15–23)": "#2a9d8f",
                 "3. night (23–07)":   "#264653"}

fig3, axes3 = plt.subplots(1, 3, figsize=(12, 7), sharex=True)
metrics = [("sys", "Systolic (mmHg)",
            [(120, "#fdd835", "Elevated"),
             (130, "#ff7f0e", "Stage 1"),
             (140, "#d62728", "Stage 2")],
            autoscale(weekly["sys"], pad=3, step=5)),
           ("dia", "Diastolic (mmHg)",
            [(80, "#ff7f0e", "Stage 1"),
             (90, "#d62728", "Stage 2")],
            autoscale(weekly["dia"], pad=3, step=5)),
           ("pulse", "Pulse (bpm)",
            [(100, "#ff7f0e", "Tachycardia")],
            autoscale(weekly["pulse"], pad=3, step=5))]

xw = list(range(len(weeks)))
for ax, (metric, label, thresholds, ylim) in zip(axes3, metrics):
    for thr, color, tlabel in thresholds:
        ax.axhline(thr, color=color, lw=1, ls="--", alpha=0.55)
        ax.text(len(weeks) - 0.95, thr + 0.4, tlabel, fontsize=8,
                color=color, ha="right", va="bottom")
    for per in period_order:
        vals = [weekly.loc[(pd.Timestamp(w), per), metric]
                if (pd.Timestamp(w), per) in weekly.index else None
                for w in weeks]
        ax.plot(xw, vals, marker="o", lw=2.2, ms=8,
                color=period_colors[per], label=per)
        for x_pos, v in zip(xw, vals):
            if v is not None:
                ax.annotate(f"{v:.0f}", (x_pos, v),
                            xytext=(0, 7), textcoords="offset points",
                            ha="center", fontsize=8,
                            color=period_colors[per], fontweight="bold")
    ax.set_title(label, fontweight="bold")
    ax.set_ylim(*ylim)
    ax.set_xticks(xw)
    ax.set_xticklabels(week_labels, rotation=0)
    ax.set_xlabel("week starting")
    ax.grid(True, alpha=0.3)
    if metric == "sys":
        ax.legend(loc="lower left", fontsize=9, framealpha=0.95)

fig3.suptitle(f"Weekly trend by 8h period — "
              f"{df['ts'].min():%d %b} → {df['ts'].max():%d %b %Y}",
              fontsize=14, fontweight="bold")
fig3.tight_layout(rect=[0, 0, 1, 0.95])
fig3.savefig("periods_weekly.png", dpi=150)

# 24-hour diurnal curve — mean ± IQR per hour-of-day for each metric.
# Useful for spotting non-dipper patterns and morning surge.
hourly = (df.assign(hour=df["ts"].dt.hour)
            .groupby("hour")
            .agg(sys_mean=("sys", "mean"),
                 sys_q1=("sys", lambda x: x.quantile(0.25)),
                 sys_q3=("sys", lambda x: x.quantile(0.75)),
                 dia_mean=("dia", "mean"),
                 dia_q1=("dia", lambda x: x.quantile(0.25)),
                 dia_q3=("dia", lambda x: x.quantile(0.75)),
                 pulse_mean=("pulse", "mean"),
                 pulse_q1=("pulse", lambda x: x.quantile(0.25)),
                 pulse_q3=("pulse", lambda x: x.quantile(0.75)),
                 n=("sys", "count"))
            .round(1))
hourly.to_csv("hourly_stats.csv")

# Morning surge proxy: max hourly mean over 06–10h minus min over 00–06h.
def _surge(metric):
    pre = hourly.loc[hourly.index < 6, f"{metric}_mean"]
    morn = hourly.loc[(hourly.index >= 6) & (hourly.index <= 10),
                      f"{metric}_mean"]
    if pre.empty or morn.empty:
        return None, None, None
    return morn.max() - pre.min(), pre.idxmin(), morn.idxmax()

surge_info = {m: _surge(m) for m in ("sys", "dia", "pulse")}
print("\nMorning surge (max 06–10h − min 00–06h):")
for m, (delta, hmin, hmax) in surge_info.items():
    if delta is not None:
        print(f"  {m:5s}  +{delta:5.1f}   (trough {hmin:02d}h → peak {hmax:02d}h)")
    else:
        print(f"  {m:5s}  (insufficient data in 00–10h window)")

fig4 = plt.figure(figsize=(12, 9))
gs = fig4.add_gridspec(4, 1, height_ratios=[3, 3, 3, 1], hspace=0.15)
diurnal_panels = [
    (gs[0], "sys",   "Systolic (mmHg)",  "#1f77b4",
     [(120, "#fdd835", "Elevated"), (130, "#ff7f0e", "Stage 1"),
      (140, "#d62728", "Stage 2")]),
    (gs[1], "dia",   "Diastolic (mmHg)", "#9467bd",
     [(80, "#ff7f0e", "Stage 1"), (90, "#d62728", "Stage 2")]),
    (gs[2], "pulse", "Pulse (bpm)",      "#e377c2",
     [(100, "#ff7f0e", "Tachycardia")]),
]
hrs = list(hourly.index)
last_ax = None
for spec, metric, label, color, thresholds in diurnal_panels:
    ax = fig4.add_subplot(spec, sharex=last_ax)
    last_ax = ax
    ax.fill_between(hrs, hourly[f"{metric}_q1"], hourly[f"{metric}_q3"],
                    color=color, alpha=0.25, label="IQR (25–75%)")
    ax.plot(hrs, hourly[f"{metric}_mean"], color=color, lw=2.2,
            marker="o", ms=6, label="hourly mean")
    for thr, tcolor, tlabel in thresholds:
        ax.axhline(thr, color=tcolor, lw=1, ls="--", alpha=0.6)
        ax.text(23.3, thr, tlabel, fontsize=8, color=tcolor,
                ha="right", va="bottom")
    mean = hourly[f"{metric}_mean"]
    if not mean.empty:
        lo_h, hi_h = mean.idxmin(), mean.idxmax()
        ax.annotate(f"min {mean[lo_h]:.0f} @ {lo_h:02d}h",
                    xy=(lo_h, mean[lo_h]), xytext=(0, -16),
                    textcoords="offset points", ha="center", fontsize=8.5,
                    color="#2e7d32", fontweight="bold")
        ax.annotate(f"max {mean[hi_h]:.0f} @ {hi_h:02d}h",
                    xy=(hi_h, mean[hi_h]), xytext=(0, 10),
                    textcoords="offset points", ha="center", fontsize=8.5,
                    color="#c62828", fontweight="bold")
    ax.set_ylabel(label, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.3)

# Sample-count bar at the bottom — shows which hours have sparse coverage.
ax_n = fig4.add_subplot(gs[3], sharex=last_ax)
ax_n.bar(hrs, hourly["n"], color="#555", alpha=0.7)
ax_n.set_ylabel("n", fontweight="bold")
ax_n.set_xlim(-0.5, 23.5)
ax_n.set_xticks(range(0, 24, 2))
ax_n.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)])
ax_n.set_xlabel("Hour of day")
ax_n.grid(True, alpha=0.3, axis="y")

fig4.suptitle(f"Diurnal pattern — mean ± IQR by hour of day  "
              f"({df['ts'].min():%d %b} → {df['ts'].max():%d %b %Y})",
              fontsize=14, fontweight="bold")
fig4.tight_layout(rect=[0, 0, 1, 0.96])
fig4.savefig("diurnal.png", dpi=150)

# === Clinical summary metrics ===
# ACC/AHA stage per individual reading.
STAGE_ORDER = ["Normal", "Elevated", "Stage 1", "Stage 2", "Crisis"]
STAGE_COLORS = {
    "Normal":   "#2ca02c",
    "Elevated": "#fdd835",
    "Stage 1":  "#ff7f0e",
    "Stage 2":  "#d62728",
    "Crisis":   "#7b1fa2",
}

def stage(s, d):
    if s >= 180 or d >= 120: return "Crisis"
    if s >= 140 or d >= 90:  return "Stage 2"
    if s >= 130 or d >= 80:  return "Stage 1"
    if s >= 120:             return "Elevated"
    return "Normal"

df["stage"] = [stage(s, d) for s, d in zip(df["sys"], df["dia"])]
stage_counts = df["stage"].value_counts().reindex(STAGE_ORDER, fill_value=0)
stage_pct = (stage_counts / len(df) * 100).round(1)

# ESH day/night convention: day 07–23, night 23–07.
_hr = df["ts"].dt.hour
day_mask = (_hr >= 7) & (_hr < 23)
night_mask = ~day_mask
day_sys, day_dia = df.loc[day_mask, "sys"].mean(), df.loc[day_mask, "dia"].mean()
night_sys, night_dia = df.loc[night_mask, "sys"].mean(), df.loc[night_mask, "dia"].mean()

def _dip(d, n):
    return (d - n) / d * 100 if d and pd.notna(d) else None

dip_sys = _dip(day_sys, night_sys)
dip_dia = _dip(day_dia, night_dia)

def _dipper_label(d):
    if d is None or pd.isna(d): return "—"
    if d > 20:  return "extreme dipper"
    if d >= 10: return "normal dipper"
    if d >= 0:  return "non-dipper"
    return "reverse dipper"

# ESH home-BP threshold: ≥135/85.
esh_above = ((df["sys"] >= 135) | (df["dia"] >= 85)).sum()
esh_above_pct = esh_above / len(df) * 100

# Per-day flags: worst stage seen that day, and whether all readings clean.
df_day = df.assign(date=df["ts"].dt.date)
by_day = df_day.groupby("date")
days_total = by_day.ngroups
def _worst(stages):
    return max(stages, key=STAGE_ORDER.index)
day_worst = by_day["stage"].agg(_worst)
days_stage2 = day_worst.isin(["Stage 2", "Crisis"]).sum()
day_all_clean = by_day.apply(
    lambda g: ((g["sys"] < 135) & (g["dia"] < 85)).all(), include_groups=False)
days_all_clean = int(day_all_clean.sum())

# Single highest systolic reading.
_max_idx = df["sys"].idxmax()
max_row = df.loc[_max_idx]

clinical = pd.DataFrame({
    "key": [
        "day_sys_mean", "day_dia_mean", "day_n",
        "night_sys_mean", "night_dia_mean", "night_n",
        "dip_sys_pct", "dip_dia_pct", "dip_pattern",
        "esh_above_n", "esh_above_pct",
        "days_total", "days_stage2", "days_all_clean",
        "max_sys", "max_dia", "max_pulse", "max_ts",
    ],
    "value": [
        f"{day_sys:.1f}", f"{day_dia:.1f}", int(day_mask.sum()),
        f"{night_sys:.1f}", f"{night_dia:.1f}", int(night_mask.sum()),
        f"{dip_sys:.1f}" if dip_sys is not None and pd.notna(dip_sys) else "—",
        f"{dip_dia:.1f}" if dip_dia is not None and pd.notna(dip_dia) else "—",
        _dipper_label(dip_sys),
        int(esh_above), f"{esh_above_pct:.1f}",
        days_total, int(days_stage2), days_all_clean,
        int(max_row["sys"]), int(max_row["dia"]), int(max_row["pulse"]),
        f"{max_row['ts']:%Y-%m-%d %H:%M}",
    ],
})
clinical.to_csv("clinical_summary.csv", index=False)

pd.DataFrame({
    "stage": STAGE_ORDER,
    "count": stage_counts.values,
    "pct":   stage_pct.values,
}).to_csv("stage_counts.csv", index=False)

# === Per-week clinical digest ===
# Re-aggregate the cover-page clinical metrics for each ISO week, so a
# clinician can scan trajectories week-by-week.
DENSITY_THRESHOLD = 3  # median readings/day to count a week as "dense"

def _week_clinical(group):
    n = len(group)
    hr_in = group["ts"].dt.hour
    day_in = (hr_in >= 7) & (hr_in < 23)
    day_sys = group.loc[day_in, "sys"].mean()
    day_dia = group.loc[day_in, "dia"].mean()
    night_sys = group.loc[~day_in, "sys"].mean()
    night_dia = group.loc[~day_in, "dia"].mean()
    night_n = int((~day_in).sum())
    dip_sys = ((day_sys - night_sys) / day_sys * 100
               if pd.notna(day_sys) and pd.notna(night_sys) and day_sys
               else None)
    hourly_g = group.assign(_h=hr_in).groupby("_h")["sys"].mean()
    pre = hourly_g.loc[hourly_g.index < 6]
    morn = hourly_g.loc[(hourly_g.index >= 6) & (hourly_g.index <= 10)]
    surge_sys = (morn.max() - pre.min()
                 if not pre.empty and not morn.empty else None)
    esh_n = int(((group["sys"] >= 135) | (group["dia"] >= 85)).sum())
    days_in_week = group["ts"].dt.date.nunique()
    days_s2 = sum(
        1 for _, gg in group.groupby(group["ts"].dt.date)
        if ((gg["sys"] >= 140) | (gg["dia"] >= 90)).any())
    per_day_counts = group.groupby(group["ts"].dt.date).size()
    rpd_median = float(per_day_counts.median()) if not per_day_counts.empty else 0.0

    # Daily means (chronological) drive ARV and streaks so the metrics
    # behave the same whether the week has 1 reading/day or 12.
    by_date = group.groupby(group["ts"].dt.date)
    daily = by_date[["sys", "dia", "pulse"]].mean().sort_index()
    def _arv(s):
        diffs = s.dropna().diff().abs().dropna()
        return round(float(diffs.mean()), 1) if not diffs.empty else None
    arv_s = _arv(daily["sys"])
    arv_d = _arv(daily["dia"])
    arv_p = _arv(daily["pulse"])

    pp_per_reading = group["sys"] - group["dia"]
    pp_mean = round(float(pp_per_reading.mean()), 1) if not pp_per_reading.empty else None
    pp_max = int(pp_per_reading.max()) if not pp_per_reading.empty else None

    # Streaks on daily means: a day is "in target" if mean sys < 135 AND mean dia < 85.
    day_in_target = (daily["sys"] < 135) & (daily["dia"] < 85)
    def _longest_run(bools):
        best = run = 0
        for v in bools:
            run = run + 1 if v else 0
            if run > best:
                best = run
        return int(best)
    streak_in = _longest_run(day_in_target.tolist())
    streak_out = _longest_run((~day_in_target).tolist())

    # Within-week trend: slope (mmHg/day or bpm/day) + 95 % CI half-width.
    # Needs at least 3 daily points; otherwise None.
    def _slope_ci(s):
        s = s.dropna()
        if len(s) < 3:
            return None, None
        x = np.array([d.toordinal() for d in s.index], dtype=float)
        x = x - x[0]
        r = linregress(x, s.values)
        return round(float(r.slope), 2), round(float(1.96 * r.stderr), 2)
    slope_s, slope_s_ci = _slope_ci(daily["sys"])
    slope_d, slope_d_ci = _slope_ci(daily["dia"])
    slope_p, slope_p_ci = _slope_ci(daily["pulse"])

    crisis_present = bool(((group["sys"] >= 180) | (group["dia"] >= 120)).any())

    # Daily-mean sys-vs-HR Pearson r; >0 means BP and HR rise/fall together.
    aligned = daily.dropna(subset=["sys", "pulse"])
    coupling_r = (round(float(aligned["sys"].corr(aligned["pulse"])), 2)
                  if len(aligned) >= 3 else None)

    # Mean arterial pressure: dia + 1/3 (sys − dia).  Perfusion pressure.
    _map = group["dia"] + (group["sys"] - group["dia"]) / 3.0
    map_mean = round(float(_map.mean()), 1) if not _map.empty else None

    # Rate-pressure product (sys × HR / 1000): myocardial workload proxy.
    _rpp = group["sys"] * group["pulse"]
    rpp_mean = round(float(_rpp.mean() / 1000.0), 2) if not _rpp.empty else None

    # Projected days until daily-mean sys crosses below 135 mmHg, but only
    # when the within-week slope is significantly negative.
    sys_m = group["sys"].mean()
    if (slope_s is not None and slope_s < 0
            and (slope_s + slope_s_ci) < 0
            and pd.notna(sys_m) and sys_m > 135):
        time_to_target_days = int(round((135 - sys_m) / slope_s))
    else:
        time_to_target_days = None

    return pd.Series({
        "n": n,
        "sys_mean":   round(group["sys"].mean(),   1),
        "dia_mean":   round(group["dia"].mean(),   1),
        "pulse_mean": round(group["pulse"].mean(), 1),
        "night_n": night_n,
        "day_sys":   round(day_sys,   1) if pd.notna(day_sys)   else None,
        "day_dia":   round(day_dia,   1) if pd.notna(day_dia)   else None,
        "night_sys": round(night_sys, 1) if pd.notna(night_sys) else None,
        "night_dia": round(night_dia, 1) if pd.notna(night_dia) else None,
        "dip_sys_pct": round(dip_sys,  1) if dip_sys   is not None else None,
        "surge_sys":   round(surge_sys, 1) if surge_sys is not None else None,
        "esh_above_n":   esh_n,
        "esh_above_pct": round(esh_n / n * 100, 1) if n else None,
        "days_in_week":  days_in_week,
        "days_stage2":   days_s2,
        "readings_per_day_median": round(rpd_median, 2),
        "is_dense": bool(rpd_median >= DENSITY_THRESHOLD),
        "arv_s": arv_s,
        "arv_d": arv_d,
        "arv_p": arv_p,
        "pp_mean": pp_mean,
        "pp_max": pp_max,
        "streak_in_target": streak_in,
        "streak_out_of_target": streak_out,
        "slope_s": slope_s, "slope_s_ci": slope_s_ci,
        "slope_d": slope_d, "slope_d_ci": slope_d_ci,
        "slope_p": slope_p, "slope_p_ci": slope_p_ci,
        "coupling_r": coupling_r,
        "map_mean": map_mean,
        "rpp_mean": rpp_mean,
        "time_to_target_days": time_to_target_days,
        "crisis_present": crisis_present,
    })

df_with_week = df.assign(
    week_start=df["ts"].dt.to_period("W-SUN").apply(lambda p: p.start_time))
weekly_clinical = (df_with_week.groupby("week_start", group_keys=True)
                   .apply(_week_clinical, include_groups=False))
weekly_clinical["d_sys"] = weekly_clinical["sys_mean"].diff().round(1)
weekly_clinical["d_dia"] = weekly_clinical["dia_mean"].diff().round(1)
weekly_clinical["d_dip"] = weekly_clinical["dip_sys_pct"].diff().round(1)

# Phenotype classification — single primary label + optional secondary tags.
# Primary rules are evaluated top-down (first match wins).
PHENOTYPE_PRIMARY = [
    "Crisis", "Uncontrolled", "Isolated-systolic", "Labile",
    "Climbing", "Borderline", "Controlled",
]
LABILE_ARV_THRESHOLD = 10        # ARV(sys) mmHg above which "Labile"
TACHY_HR_THRESHOLD = 80
BRADY_HR_THRESHOLD = 55
WIDE_PP_THRESHOLD = 60

def classify_week(row, prev, prev2):
    sys_m, dia_m = row["sys_mean"], row["dia_mean"]
    if row.get("crisis_present"):
        primary = "Crisis"
    elif sys_m >= 140 or dia_m >= 90:
        primary = "Uncontrolled"
    elif sys_m >= 135 and dia_m < 85 and (row.get("pp_mean") or 0) >= WIDE_PP_THRESHOLD:
        primary = "Isolated-systolic"
    elif (sys_m < 135 and dia_m < 85
          and pd.notna(row.get("arv_s"))
          and row["arv_s"] > LABILE_ARV_THRESHOLD):
        primary = "Labile"
    elif ((prev is not None and prev2 is not None
           and (sys_m - prev["sys_mean"]) >= 3
           and (prev["sys_mean"] - prev2["sys_mean"]) >= 3)
          or (pd.notna(row.get("slope_s"))
              and row["slope_s"] > 0
              and (row["slope_s"] - row["slope_s_ci"]) > 0)):
        primary = "Climbing"
    elif 130 <= sys_m < 140 or 80 <= dia_m < 90:
        primary = "Borderline"
    else:
        primary = "Controlled"

    secondary = []
    hr = row.get("pulse_mean")
    if pd.notna(hr) and hr >= TACHY_HR_THRESHOLD:
        secondary.append("Tachycardia")
    if pd.notna(hr) and hr < BRADY_HR_THRESHOLD:
        secondary.append("Bradycardia")
    pp = row.get("pp_mean")
    if (pd.notna(pp) and pp >= WIDE_PP_THRESHOLD
            and primary != "Isolated-systolic"):
        secondary.append("Wide-PP")
    return primary, ";".join(secondary)

_primaries, _secondaries = [], []
for i in range(len(weekly_clinical)):
    row = weekly_clinical.iloc[i]
    prev  = weekly_clinical.iloc[i - 1] if i >= 1 else None
    prev2 = weekly_clinical.iloc[i - 2] if i >= 2 else None
    p, s = classify_week(row, prev, prev2)
    _primaries.append(p)
    _secondaries.append(s)
weekly_clinical["phenotype_primary"] = _primaries
weekly_clinical["phenotype_secondary"] = _secondaries

weekly_clinical.to_csv("weekly_clinical_summary.csv")

# Distribution of phenotypes across the reporting window (for the cover page).
_phen_counts = weekly_clinical["phenotype_primary"].value_counts()
_phen_summary = " · ".join(
    f"{name}×{int(_phen_counts[name])}"
    for name in PHENOTYPE_PRIMARY if name in _phen_counts.index)

# Window-wide aggregates (computed on daily means across the full window
# so they behave consistently regardless of sampling density).
_full_daily = (df.set_index("ts").resample("D")[["sys", "dia", "pulse"]]
                 .mean().dropna(subset=["sys"]))
def _window_arv(s):
    diffs = s.dropna().diff().abs().dropna()
    return round(float(diffs.mean()), 1) if not diffs.empty else None
window_arv_s = _window_arv(_full_daily["sys"])
window_arv_d = _window_arv(_full_daily["dia"])
window_arv_p = _window_arv(_full_daily["pulse"])
window_pp_mean = round(float((df["sys"] - df["dia"]).mean()), 1)
window_pp_max = int((df["sys"] - df["dia"]).max())

_in_target = ((_full_daily["sys"] < 135) & (_full_daily["dia"] < 85)).tolist()
def _longest(bools):
    best = run = 0
    for v in bools:
        run = run + 1 if v else 0
        if run > best:
            best = run
    return int(best)
window_streak_in  = _longest(_in_target)
window_streak_out = _longest([not v for v in _in_target])
dense_weeks_n = int(weekly_clinical["is_dense"].sum())

clinical = pd.concat([clinical, pd.DataFrame({
    "key": [
        "phenotype_summary", "weeks_total", "dense_weeks_n",
        "window_arv_s", "window_arv_d", "window_arv_p",
        "window_pp_mean", "window_pp_max",
        "window_streak_in", "window_streak_out",
    ],
    "value": [
        _phen_summary, len(weekly_clinical), dense_weeks_n,
        window_arv_s if window_arv_s is not None else "—",
        window_arv_d if window_arv_d is not None else "—",
        window_arv_p if window_arv_p is not None else "—",
        window_pp_mean, window_pp_max,
        window_streak_in, window_streak_out,
    ],
})], ignore_index=True)
clinical.to_csv("clinical_summary.csv", index=False)

print(f"\nClinical headline numbers:")
print(f"  Day {day_sys:.1f}/{day_dia:.1f} (n={int(day_mask.sum())})  "
      f"Night {night_sys:.1f}/{night_dia:.1f} (n={int(night_mask.sum())})")
print(f"  Nocturnal dip: sys {dip_sys:.1f}%  dia {dip_dia:.1f}%  "
      f"({_dipper_label(dip_sys)})")
print(f"  ESH ≥135/85: {esh_above} of {len(df)} readings ({esh_above_pct:.1f}%)")
print(f"  Days with ≥1 Stage-2: {int(days_stage2)}/{days_total}, "
      f"all-clean days: {days_all_clean}/{days_total}")

# === Time-in-range chart ===
# Per-day stacked stage distribution, faceted by calendar month (top row)
# and by ISO week (bottom row).  The overall-window proportions live on
# the cover-page READING DISTRIBUTION table.
from collections import defaultdict
from calendar import month_name

days_sorted = sorted(by_day.groups.keys())
day_pcts_by_date = {}
for d in days_sorted:
    g = df_day[df_day["date"] == d]
    total = len(g)
    day_pcts_by_date[d] = {s: (g["stage"] == s).sum() / total * 100
                           for s in STAGE_ORDER}

days_by_month = defaultdict(list)
for d in days_sorted:
    days_by_month[(d.year, d.month)].append(d)
months_order = sorted(days_by_month.keys())

days_by_week = defaultdict(list)
for d in days_sorted:
    week_start = pd.Timestamp(d).to_period("W-SUN").start_time.date()
    days_by_week[week_start].append(d)
weeks_order = sorted(days_by_week.keys())

def _stack_panel(ax, days, *, title, xfmt="%d"):
    bottom = [0.0] * len(days)
    for s in STAGE_ORDER:
        heights = [day_pcts_by_date[d][s] for d in days]
        if sum(heights) <= 0:
            continue
        ax.bar(range(len(days)), heights, bottom=bottom,
               color=STAGE_COLORS[s], width=0.85, label=s,
               edgecolor="white", lw=0.3)
        bottom = [b + h for b, h in zip(bottom, heights)]
    ax.set_xticks(range(len(days)))
    ax.set_xticklabels([f"{d:{xfmt}}" for d in days],
                       rotation=0, fontsize=7)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 50, 100])
    ax.set_yticklabels(["0", "50", "100"], fontsize=7)
    ax.set_title(title, fontsize=10, fontweight="bold", pad=4)
    ax.tick_params(axis="x", length=0)

fig5 = plt.figure(figsize=(14, 9))
outer = fig5.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.45)

gs_m = outer[0].subgridspec(1, len(months_order),
                            width_ratios=[len(days_by_month[m])
                                          for m in months_order],
                            wspace=0.15)
for i, m in enumerate(months_order):
    ax = fig5.add_subplot(gs_m[0, i])
    _stack_panel(ax, days_by_month[m],
                 title=f"{month_name[m[1]]} {m[0]}", xfmt="%d")
    if i == 0:
        ax.set_ylabel("% of day's readings", fontsize=8)

gs_w = outer[1].subgridspec(1, len(weeks_order),
                            width_ratios=[len(days_by_week[w])
                                          for w in weeks_order],
                            wspace=0.20)
for i, w in enumerate(weeks_order):
    ax = fig5.add_subplot(gs_w[0, i])
    _stack_panel(ax, days_by_week[w],
                 title=f"Week of {w:%d %b}", xfmt="%d")
    if i == 0:
        ax.set_ylabel("% of day's readings", fontsize=8)

# Single legend for the whole figure.
legend_handles = [plt.Rectangle((0, 0), 1, 1, color=STAGE_COLORS[s])
                  for s in STAGE_ORDER if any(day_pcts_by_date[d][s] > 0
                                              for d in days_sorted)]
legend_labels = [s for s in STAGE_ORDER
                 if any(day_pcts_by_date[d][s] > 0 for d in days_sorted)]
fig5.legend(legend_handles, legend_labels,
            loc="lower center", ncol=len(legend_labels),
            fontsize=9, frameon=False, bbox_to_anchor=(0.5, 0.01))
fig5.tight_layout(rect=[0.01, 0.04, 0.99, 1.0])
fig5.savefig("time_in_range.png", dpi=150, bbox_inches="tight")

plt.style.use("seaborn-v0_8-whitegrid")
fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

sys_lim = autoscale(df["sys"])
dia_lim = autoscale(df["dia"])
pulse_lim = autoscale(df["pulse"])

panels = [
    ("sys",   "Systolic (mmHg)",  "#1f77b4", sys_lim,
     [(sys_lim[0], 120,        "#2ca02c", "Normal"),
      (120,        130,        "#fdd835", "Elevated"),
      (130,        140,        "#ff7f0e", "Stage 1"),
      (140,        sys_lim[1], "#d62728", "Stage 2")]),
    ("dia",   "Diastolic (mmHg)", "#9467bd", dia_lim,
     [(dia_lim[0], 80,         "#2ca02c", "Normal"),
      (80,         90,         "#ff7f0e", "Stage 1"),
      (90,         dia_lim[1], "#d62728", "Stage 2")]),
    ("pulse", "Pulse (bpm)",      "#e377c2", pulse_lim,
     [(pulse_lim[0], 100,        "#2ca02c", "Resting"),
      (100,          pulse_lim[1], "#ff7f0e", "Tachycardia")]),
]

for ax, (col, label, color, (ymin, ymax), bands) in zip(axes, panels):
    for lo, hi, bc, blabel in bands:
        ax.axhspan(lo, hi, color=bc, alpha=0.15)
        ax.text(0.995, (hi - 1 - ymin) / (ymax - ymin), blabel,
                transform=ax.transAxes, ha="right", va="top",
                fontsize=8, color="#555")
    ax.plot(df["ts"], df[col], color=color, lw=0.6, alpha=0.4, zorder=2)
    ax.scatter(df["ts"], df[col], s=8, color=color, alpha=0.7, zorder=3)
    ax.plot(daily.index, daily[col], color="black", lw=1.2, alpha=0.55,
            zorder=4, label="daily mean")
    ax.scatter(daily.index, daily[col], s=14, color="black", alpha=0.55,
               zorder=5)
    ax.plot(rolling.index, rolling[col], color="#d62728", lw=2.6, zorder=6,
            label="7-day rolling avg")
    ax.set_ylim(ymin, ymax)
    ax.set_ylabel(label, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)

def top_spikes(series_df, col, n=2, min_gap_hours=12):
    s = series_df.sort_values(col, ascending=False)
    picked = []
    for ts, val in zip(s["ts"], s[col]):
        if all(abs((ts - p[0]).total_seconds()) / 3600 >= min_gap_hours
               for p in picked):
            picked.append((ts, val))
            if len(picked) == n:
                break
    return picked

for ax, (col, *_), in zip(axes, panels):
    for ts, val in top_spikes(df, col):
        ax.annotate(f"{val} @ {ts:%d %b %H:%M}",
                    xy=(ts, val), xytext=(10, 14), textcoords="offset points",
                    fontsize=8.5, color="#b30000", fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#b30000", lw=1),
                    bbox=dict(boxstyle="round,pad=0.25", fc="white",
                              ec="#b30000", lw=0.8, alpha=0.9))

axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=3))
axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
plt.setp(axes[-1].xaxis.get_majorticklabels(), rotation=30, ha="right")

t0, t1 = df["ts"].min(), df["ts"].max()
fig.suptitle(f"Blood pressure & pulse — {t0:%d %b %Y} to {t1:%d %b %Y}  "
             f"({len(df)} readings, {len(daily)} days)",
             fontsize=14, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.97])
fig.savefig("vitals.png", dpi=150)
fig.savefig("vitals.pdf")
print(f"\nwrote vitals.png, vitals.pdf, daily_stats.csv, period_stats.csv, "
      f"periods.png, periods_weekly.png, weekly_period_stats.csv, "
      f"diurnal.png, hourly_stats.csv, clinical_summary.csv, "
      f"stage_counts.csv, time_in_range.png, "
      f"weekly_clinical_summary.csv  "
      f"({len(df)} readings, {len(daily)} days)")
