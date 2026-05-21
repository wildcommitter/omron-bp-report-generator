#!/usr/bin/env python3
"""Plot systolic, diastolic and pulse from input.csv (OMRON Spanish export)."""
import math

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def autoscale(values, pad=5, step=10):
    """Round (min-pad, max+pad) outwards to multiples of step."""
    lo = math.floor((min(values) - pad) / step) * step
    hi = math.ceil((max(values) + pad) / step) * step
    return lo, hi

MONTHS = {"ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,
          "jul":7,"ago":8,"sep":9,"oct":10,"nov":11,"dic":12}

def parse_dt(d, t):
    parts = d.replace(".", "").split()
    return pd.Timestamp(int(parts[2]), MONTHS[parts[1].lower()], int(parts[0]),
                        int(t.split(":")[0]), int(t.split(":")[1]))

df = pd.read_csv("input.csv")
df = df[pd.to_numeric(df["Sistólica (mmHg)"], errors="coerce").notna()].copy()
df["ts"] = [parse_dt(d, t) for d, t in zip(df["Fecha"], df["Hora"])]
df = df.rename(columns={"Sistólica (mmHg)": "sys",
                        "Diastólica (mmHg)": "dia",
                        "Pulso (ppm)": "pulse"})
df = df[["ts", "sys", "dia", "pulse"]].astype(
    {"sys": int, "dia": int, "pulse": int}).sort_values("ts")

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
      f"periods.png, periods_weekly.png, weekly_period_stats.csv  "
      f"({len(df)} readings, {len(daily)} days)")
