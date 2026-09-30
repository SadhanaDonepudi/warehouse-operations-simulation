"""Warehouse Operations Simulation — discrete-event model (SimPy).

Simulates one operating day of a warehouse order pipeline:

    receiving -> picking -> packing -> shipping

Orders arrive through the day as a non-homogeneous Poisson process
(peak-day demand profile). Each stage is staffed by a labor pool modeled
as a SimPy ``Container`` of worker tokens. A stage's headcount can follow
a time-of-day schedule, which is how shift-policy scenarios (e.g. a
mid-day labor surge aligned to the demand peak) are represented: staff
going off-shift finish their current task before a token is withdrawn,
and additional staff are added as tokens at their scheduled start.

An order's cycle time runs from its arrival until it ships. Orders that
ship after the end of the 10-hour shift count against the same-day ship
target.

All demand and process parameters are synthetic; see README.md.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import simpy

STAGES = ("receiving", "picking", "packing", "shipping")

# Timeline (minutes from 08:00). Orders are released over the first 8
# hours; the shift runs 10 hours, so late-arriving orders have a
# 2-hour buffer to clear the pipeline and still ship same-day.
ARRIVAL_WINDOW_MIN = 480.0
SHIFT_END_MIN = 600.0

# Mid-day demand peak window (10:30-15:30) -- used for peak-window
# utilization, which is where a flat staffing plan hurts most and a
# peak-aligned shift helps.
PEAK_WINDOW = (150.0, 450.0)

# Peak-day demand profile: orders per hour for 08:00-16:00 (~600 orders/day
# in expectation, peaking at 99 orders/hour around midday). At this volume
# the baseline plan runs picking hot (~90% utilization), so same-day ship
# performance is genuinely at risk -- the situation the labor plans and
# automation scenario are meant to relieve.
HOURLY_ARRIVAL_RATES = [56, 68, 85, 104, 99, 85, 74, 61]


def _lognormal_time(rng: random.Random, mean: float, cv: float) -> float:
    """Draw a positive service time (minutes) with the given mean and CV."""
    sigma2 = math.log(1.0 + cv * cv)
    mu = math.log(mean) - sigma2 / 2.0
    # Cap at 4x the mean to tame the lognormal tail.
    return min(rng.lognormvariate(mu, math.sqrt(sigma2)), 4.0 * mean)


@dataclass
class StageConfig:
    """Staffing and service-time parameters for one pipeline stage.

    ``staff_schedule`` is a list of ``(start_min, end_min, headcount)``
    windows. ``per_line_minutes`` (picking only) makes the service time
    scale with the number of lines on the order instead of a fixed mean.
    """

    name: str
    staff_schedule: list
    mean_minutes: float = 0.0
    cv: float = 0.4
    per_line_minutes: float | None = None

    @property
    def max_staff(self) -> int:
        return max(n for _, _, n in self.staff_schedule)

    @property
    def scheduled_staff_minutes(self) -> float:
        return float(sum(n * (end - start) for start, end, n in self.staff_schedule))

    @property
    def peak_window_staff_minutes(self) -> float:
        w0, w1 = PEAK_WINDOW
        total = 0.0
        for start, end, n in self.staff_schedule:
            overlap = min(end, w1) - max(start, w0)
            if overlap > 0:
                total += n * overlap
        return float(total)

    def service_mean(self, lines: int) -> float:
        if self.per_line_minutes is not None:
            return self.per_line_minutes * lines
        return self.mean_minutes


@dataclass
class Scenario:
    name: str
    label: str
    description: str
    stages: dict  # stage name -> StageConfig


@dataclass
class DayStats:
    cycle_times: list = field(default_factory=list)
    ship_times: list = field(default_factory=list)
    busy_minutes: dict = field(default_factory=lambda: {s: 0.0 for s in STAGES})
    window_busy_minutes: dict = field(default_factory=lambda: {s: 0.0 for s in STAGES})
    wait_minutes: dict = field(default_factory=lambda: {s: [] for s in STAGES})
    orders_arrived: int = 0


def _staff_scheduler(env: simpy.Environment, pool: simpy.Container, schedule: list):
    """Apply a stage's time-of-day staffing windows to its labor pool."""
    on_duty = schedule[0][2]
    for start, _end, staff in schedule[1:]:
        yield env.timeout(start - env.now)
        diff = staff - on_duty
        if diff > 0:
            yield pool.put(diff)
        elif diff < 0:
            # Workers finish their current task before going off-shift:
            # the get() below only completes as tokens free up.
            yield pool.get(-diff)
        on_duty = staff


def _arrival_generator(env, pools, stage_cfg, stage_rngs, stats, seed):
    """Release orders by thinning a homogeneous Poisson process."""
    rng = random.Random(seed)
    max_rate_per_min = max(HOURLY_ARRIVAL_RATES) / 60.0
    t = 0.0
    while True:
        t += rng.expovariate(max_rate_per_min)
        if t >= ARRIVAL_WINDOW_MIN:
            return
        yield env.timeout(t - env.now)
        hour = int(t // 60)
        if rng.random() >= HOURLY_ARRIVAL_RATES[hour] / max(HOURLY_ARRIVAL_RATES):
            continue
        # Order size in lines (drives picking work); clipped normal, mean ~5.
        lines = int(round(rng.gauss(5.0, 2.2)))
        lines = max(1, min(14, lines))
        stats.orders_arrived += 1
        env.process(
            _order_process(env, pools, stage_cfg, stage_rngs, stats, lines, env.now)
        )


def _order_process(env, pools, stage_cfg, stage_rngs, stats, lines, arrival_time):
    """Move one order through receiving -> picking -> packing -> shipping."""
    for stage in STAGES:
        cfg = stage_cfg[stage]
        pool = pools[stage]
        requested_at = env.now
        yield pool.get(1)
        stats.wait_minutes[stage].append(env.now - requested_at)
        service = _lognormal_time(
            stage_rngs[stage], cfg.service_mean(lines), cfg.cv
        )
        service_start = env.now
        yield env.timeout(service)
        stats.busy_minutes[stage] += env.now - service_start
        w0, w1 = PEAK_WINDOW
        overlap = min(env.now, w1) - max(service_start, w0)
        if overlap > 0:
            stats.window_busy_minutes[stage] += overlap
        yield pool.put(1)
    stats.ship_times.append(env.now)
    stats.cycle_times.append(env.now - arrival_time)


def run_day(scenario: Scenario, seed: int):
    """Simulate one warehouse day under ``scenario``.

    Returns ``(summary, cycle_times)`` where ``summary`` is a dict of
    per-day metrics. RNG streams are seeded per replication and per
    stage so scenarios share common random numbers (same arrival stream
    and comparable service draws), which sharpens the comparison.
    """
    env = simpy.Environment()
    pools = {}
    for stage in STAGES:
        cfg = scenario.stages[stage]
        pool = simpy.Container(
            env, capacity=cfg.max_staff, init=cfg.staff_schedule[0][2]
        )
        pools[stage] = pool
        if len(cfg.staff_schedule) > 1:
            env.process(_staff_scheduler(env, pool, cfg.staff_schedule))

    stats = DayStats()
    stage_rngs = {
        stage: random.Random(seed * 1000 + idx * 7919 + 17)
        for idx, stage in enumerate(STAGES)
    }
    env.process(
        _arrival_generator(env, pools, scenario.stages, stage_rngs, stats, seed + 4242)
    )
    env.run()

    ct = sorted(stats.cycle_times)
    n = len(ct)

    def pct(p):
        return float(ct[min(n - 1, int(p * n))]) if n else 0.0

    utilization = {
        stage: stats.busy_minutes[stage]
        / scenario.stages[stage].scheduled_staff_minutes
        for stage in STAGES
    }
    window_utilization = {
        stage: stats.window_busy_minutes[stage]
        / scenario.stages[stage].peak_window_staff_minutes
        for stage in STAGES
    }
    same_day = sum(1 for t in stats.ship_times if t <= SHIFT_END_MIN)
    summary = {
        "orders_arrived": stats.orders_arrived,
        "orders_shipped": n,
        "same_day_shipped": same_day,
        "late_shipped": n - same_day,
        "same_day_ship_rate": (same_day / n) if n else 0.0,
        "cycle_mean_min": float(sum(ct) / n) if n else 0.0,
        "cycle_p50_min": pct(0.50),
        "cycle_p95_min": pct(0.95),
        "avg_picking_wait_min": (
            float(sum(stats.wait_minutes["picking"]) / len(stats.wait_minutes["picking"]))
            if stats.wait_minutes["picking"]
            else 0.0
        ),
        "makespan_min": float(env.now),
    }
    for stage in STAGES:
        summary[f"util_{stage}"] = float(utilization[stage])
        summary[f"util_window_{stage}"] = float(window_utilization[stage])
    summary["peak_utilization"] = float(max(utilization.values()))
    summary["peak_window_utilization"] = float(max(window_utilization.values()))
    return summary, stats.cycle_times
