"""Run the warehouse operations Monte Carlo comparison.

Usage (from the project root):

    python run_simulation.py [--reps N] [--seed S]

Writes to outputs/:
    scenario_summary.csv       mean +/- 95% CI per scenario
    replication_results.csv    one row per simulated day
    cycle_times_sample.csv     per-order cycle times (first 25 reps/scenario)
    scenario_results.json      configs, summary, headline deltas
    figures/scenario_comparison.png
    figures/cycle_time_distribution.png
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

from experiments import headline_deltas, run_monte_carlo, summarize  # noqa: E402
from scenarios import all_scenarios  # noqa: E402
from warehouse_sim import STAGES  # noqa: E402

PROJECT_ROOT = Path(__file__).parent
OUTPUTS = PROJECT_ROOT / "outputs"
FIGURES = OUTPUTS / "figures"


def make_charts(summary_df: pd.DataFrame, cycle_sample: dict) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    labels = {
        "baseline": "Baseline",
        "amr_automation": "AMR automation",
        "shift_policy": "Peak-aligned shift",
    }
    order = [s for s in labels if s in set(summary_df["scenario"])]
    s = summary_df.set_index("scenario").loc[order]
    x = [labels[k] for k in order]

    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    panels = [
        ("same_day_shipped", "Same-day orders shipped / day", axes[0, 0]),
        ("cycle_mean_min", "Avg order cycle time (min)", axes[0, 1]),
        ("cycle_p95_min", "P95 order cycle time (min)", axes[1, 0]),
        ("peak_utilization", "Peak stage utilization", axes[1, 1]),
    ]
    for metric, title, ax in panels:
        means = s[f"{metric}_mean"]
        errs = s[f"{metric}_ci95"]
        ax.bar(x, means, yerr=errs, capsize=4, color=["#7f7f7f", "#2c7fb8", "#41ab5d"])
        ax.set_title(title)
        ax.tick_params(axis="x", labelrotation=12)
        if metric == "peak_utilization":
            ax.axhline(0.85, color="red", linestyle="--", linewidth=1,
                       label="85% utilization ceiling")
            ax.set_ylim(0, 1.0)
            ax.legend(fontsize=8)
        for i, v in enumerate(means):
            ax.text(i, v + errs.iloc[i] + 0.015 * max(means), f"{v:.2f}" if v < 10
                    else f"{v:.0f}", ha="center", fontsize=9)
    fig.suptitle("Warehouse operations simulation — scenario comparison (Monte Carlo means, 95% CI)")
    fig.tight_layout()
    fig.savefig(FIGURES / "scenario_comparison.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    for name in order:
        ax.hist(cycle_sample[name], bins=40, alpha=0.45, label=labels[name])
    ax.set_xlabel("Order cycle time (min, arrival -> shipped)")
    ax.set_ylabel("Orders")
    ax.set_title("Order cycle-time distribution by scenario (sampled replications)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "cycle_time_distribution.png", dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=500,
                        help="Monte Carlo replications per scenario (default 500)")
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()

    scenarios = all_scenarios()
    print(f"Running {args.reps} replications x {len(scenarios)} scenarios "
          f"(seed={args.seed}) ...")
    started = time.time()
    replications_df, cycle_sample = run_monte_carlo(
        scenarios, args.reps, base_seed=args.seed
    )
    elapsed = time.time() - started
    print(f"Simulation finished in {elapsed:.1f}s")

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    replications_df.to_csv(OUTPUTS / "replication_results.csv", index=False)

    summary_df = summarize(replications_df)
    summary_df.to_csv(OUTPUTS / "scenario_summary.csv", index=False)

    sample_rows = [
        {"scenario": name, "cycle_time_min": ct}
        for name, times in cycle_sample.items()
        for ct in times
    ]
    pd.DataFrame(sample_rows).to_csv(OUTPUTS / "cycle_times_sample.csv", index=False)

    deltas = headline_deltas(summary_df)
    results = {
        "seed": args.seed,
        "replications_per_scenario": args.reps,
        "runtime_seconds": round(elapsed, 1),
        "scenarios": [
            {
                "name": sc.name,
                "label": sc.label,
                "description": sc.description,
                "stages": {
                    stage: {
                        "staff_schedule": sc.stages[stage].staff_schedule,
                        "mean_minutes": sc.stages[stage].mean_minutes,
                        "per_line_minutes": sc.stages[stage].per_line_minutes,
                        "cv": sc.stages[stage].cv,
                        "scheduled_staff_minutes": sc.stages[stage].scheduled_staff_minutes,
                    }
                    for stage in STAGES
                },
            }
            for sc in scenarios
        ],
        "summary": json.loads(summary_df.to_json(orient="records")),
        "headline_deltas_vs_baseline_pct": deltas,
    }
    with open(OUTPUTS / "scenario_results.json", "w") as f:
        json.dump(results, f, indent=2)

    make_charts(summary_df, cycle_sample)

    s = summary_df.set_index("scenario")
    print("\n=== Headline results (Monte Carlo means) ===")
    for name in s.index:
        r = s.loc[name]
        print(
            f"{name:>14}: same-day shipped {r['same_day_shipped_mean']:.0f}/day, "
            f"avg cycle {r['cycle_mean_min_mean']:.1f} min, "
            f"p95 {r['cycle_p95_min_mean']:.0f} min, "
            f"peak util {r['peak_utilization_mean']:.1%} "
            f"(peak window {r['peak_window_utilization_mean']:.1%}), "
            f"same-day rate {r['same_day_ship_rate_mean']:.1%}"
        )
    for name, d in deltas.items():
        print(
            f"{name} vs baseline: same-day shipped {d['same_day_shipped_pct_change']:+.1f}%, "
            f"avg cycle {d['cycle_mean_pct_change']:+.1f}%, "
            f"p95 cycle {d['cycle_p95_pct_change']:+.1f}%"
        )
    print(f"\nOutputs written to {OUTPUTS}")


if __name__ == "__main__":
    main()
