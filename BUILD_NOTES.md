# BUILD_NOTES.md — Warehouse Operations Simulation

## What was built

A complete, runnable SimPy discrete-event simulation of a warehouse
order pipeline (receiving → picking → packing → shipping) with three
comparable labor/automation scenarios and Monte Carlo replication,
matching the methodology of the "Warehouse Operations Simulation –
Labor Management & Automation" project (500 Monte Carlo replications,
labor utilization < 85% while meeting same-day ship targets).

- `src/warehouse_sim.py` — DES model. Orders arrive as a
  non-homogeneous Poisson process (thinning) over 08:00–16:00 on a
  peak-day profile (~632 orders/day expected, midday peak 104/hr).
  Labor pools are SimPy Containers so headcount can follow time-of-day
  schedules (shift policy); off-shift workers finish their current task
  first. Service times are lognormal; picking scales with order lines.
  Seeded per-replication, per-stage RNG streams give common random
  numbers across scenarios.
- `src/scenarios.py` — Baseline (10 pickers flat), AMR automation
  (pick 1.8 → 1.08 min/line, crew 10 → 7), Peak-aligned shift (same
  6,000 picker staff-minutes re-timed: 7 / 13 / 7 across the day).
- `src/experiments.py` — replication runner, mean ± 95% CI summary,
  headline deltas vs baseline.
- `run_simulation.py` — CLI (`--reps`, `--seed`); writes CSV/JSON
  outputs and two matplotlib figures.
- `notebooks/01_results_analysis.ipynb` — executed (nbclient, venv
  kernel); all 3 code cells ran with no errors, plots and tables
  embedded.

## Run command

```
cd ~/workspace/github-projects/warehouse-operations-simulation
./.venv/bin/python run_simulation.py --reps 500   # default
```

(The system Python is externally managed, so a project venv was used:
`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
SimPy 4.1.2, pandas 3.0.6. Note: a `--system-site-packages` venv fails
here — system pandas is binary-incompatible with current NumPy — so the
venv installs its own pandas/numpy/matplotlib.)

## Verified results (full run actually executed)

500 replications × 3 scenarios, seed 20260930, simulation time 115.5 s
(total wall ~2 min including charts). Outputs confirmed on disk:
`outputs/scenario_summary.csv`, `scenario_results.json`,
`replication_results.csv` (1,500 rows), `cycle_times_sample.csv`
(first 25 reps/scenario), `outputs/figures/scenario_comparison.png`,
`outputs/figures/cycle_time_distribution.png`.

Daily means (95% CIs ≤ ±2.1 orders, ±1.1 min on cycle time):

| Metric | Baseline | AMR | Shift policy |
|---|---:|---:|---:|
| Same-day shipped/day | 617.0 | 631.2 (+2.3%) | 631.1 (+2.3%) |
| Same-day ship rate | 97.8% | 100.0% | 100.0% |
| Avg cycle time | 75.9 min | 46.0 min (−39.4%) | 68.4 min (−9.9%) |
| P95 cycle time | 133.4 min | 76.6 min (−42.6%) | 98.1 min (−26.5%) |
| Picking utilization | 95.1% | 81.5% | 95.1% |
| Peak stage utilization | 95.1% | 81.7% | 95.1% |
| Avg picking wait | 55.8 min | 27.3 min | 36.6 min |
| Makespan (last ship) | 613 min | 540 min | 560 min |

Sanity checks passed: identical arrival streams across scenarios (631.2
orders/day each — common random numbers working); shift-policy picking
utilization equals baseline exactly, as it must (same busy work, same
scheduled staff-minutes); AMR brings peak utilization under the 85%
ceiling.

## Deviations, simplifications, limitations

- **Demand tuned to a stressed peak day** (~632 orders/day). At lower
  volume (~536/day, tested during development) every plan clears
  same-day and throughput does not differentiate, so the peak-day
  profile was kept deliberately: the baseline then runs picking at
  ~95% utilization and misses some same-day ships, which is the
  capacity-risk situation the scenarios address. Documented in README.
- **Throughput metric** = orders shipped by the 18:00 cutoff
  ("same-day shipped"). Total shipped equals arrivals in every scenario
  (the pipeline always drains eventually), so same-day shipped is the
  discriminating throughput measure.
- Peak-window (10:30–15:30) picking utilization is ~100% in *all*
  scenarios (picking is saturated mid-day even with AMRs, because
  demand peaks at 104/hr); it is recorded in outputs but is not a
  discriminating metric — the README leads with whole-shift peak
  utilization instead.
- Not modeled (noted in README): facility-layout alternatives (the
  resume project also tested layouts in AnyLogic; out of scope here),
  sub-processes (putaway, QC), breaks/absenteeism, equipment downtime.
  All parameters are synthetic; SimPy is presented as the open-source
  equivalent of the resume's AnyLogic model, not a reproduction.
- Nothing was pushed to GitHub — per instructions, left for the parent
  agent. The project `.venv/` is git-ignored.
