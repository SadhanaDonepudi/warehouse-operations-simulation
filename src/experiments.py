"""Monte Carlo experiment runner for the warehouse simulation.

Runs each scenario for ``replications`` independent simulated days
(common random numbers across scenarios: replication *r* of every
scenario sees the same seeded arrival stream), aggregates the per-day
metrics, and computes headline deltas versus the baseline scenario.
"""

from __future__ import annotations

import math

import pandas as pd

from warehouse_sim import run_day

SUMMARY_METRICS = [
    "orders_arrived",
    "orders_shipped",
    "same_day_shipped",
    "late_shipped",
    "same_day_ship_rate",
    "cycle_mean_min",
    "cycle_p50_min",
    "cycle_p95_min",
    "avg_picking_wait_min",
    "makespan_min",
    "util_receiving",
    "util_picking",
    "util_packing",
    "util_shipping",
    "util_window_picking",
    "peak_utilization",
    "peak_window_utilization",
]


def run_monte_carlo(scenarios, replications: int, base_seed: int = 20260930,
                    cycle_sample_reps: int = 25):
    """Run all scenarios; return (per-replication DataFrame, cycle-time sample)."""
    rows = []
    cycle_sample = {}
    for scenario in scenarios:
        sampled = []
        for rep in range(replications):
            summary, cycle_times = run_day(scenario, seed=base_seed + rep)
            summary["scenario"] = scenario.name
            summary["replication"] = rep
            rows.append(summary)
            if rep < cycle_sample_reps:
                sampled.extend(cycle_times)
        cycle_sample[scenario.name] = sampled
    return pd.DataFrame(rows), cycle_sample


def summarize(replications_df: pd.DataFrame) -> pd.DataFrame:
    """Mean and 95% CI half-width per scenario for each metric."""
    out = []
    for scenario, group in replications_df.groupby("scenario", sort=False):
        row = {"scenario": scenario}
        n = len(group)
        for metric in SUMMARY_METRICS:
            values = group[metric].astype(float)
            row[f"{metric}_mean"] = values.mean()
            if n > 1:
                row[f"{metric}_ci95"] = 1.96 * values.std(ddof=1) / math.sqrt(n)
            else:
                row[f"{metric}_ci95"] = 0.0
        out.append(row)
    return pd.DataFrame(out)


def headline_deltas(summary_df: pd.DataFrame) -> dict:
    """Percentage deltas versus baseline for the headline metrics."""
    idx = summary_df.set_index("scenario")

    def pct_change(scenario, metric):
        base = idx.loc["baseline", metric]
        return float((idx.loc[scenario, metric] - base) / base * 100.0)

    deltas = {}
    for scenario in summary_df["scenario"]:
        if scenario == "baseline":
            continue
        deltas[scenario] = {
            "same_day_shipped_pct_change": pct_change(scenario, "same_day_shipped_mean"),
            "cycle_mean_pct_change": pct_change(scenario, "cycle_mean_min_mean"),
            "cycle_p95_pct_change": pct_change(scenario, "cycle_p95_min_mean"),
            "peak_utilization": float(idx.loc[scenario, "peak_utilization_mean"]),
            "pickers": None,  # filled by caller if desired
        }
    return deltas
