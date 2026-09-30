"""Scenario definitions for the warehouse operations simulation.

Three labor / automation plans are compared on the same peak-day demand:

1. ``baseline``       -- conventional labor plan, manual picking.
2. ``amr_automation`` -- autonomous mobile robots (AMRs) assist picking:
                         fetch travel is largely removed from the picker's
                         task (pick time per line falls ~40%) and the
                         picking crew is smaller.
3. ``shift_policy``   -- same total picker labor-hours as baseline, but
                         re-timed into a mid-day surge aligned with the
                         demand peak (peak-aligned shift).

Other stages keep baseline staffing in all scenarios so differences are
attributable to the change being tested.
"""

from warehouse_sim import Scenario, StageConfig

DAY = (0, 600)  # 10-hour shift, minutes from 08:00


def _receiving():
    return StageConfig("receiving", [(0, 600, 6)], mean_minutes=3.0, cv=0.35)


def _packing():
    return StageConfig("packing", [(0, 600, 6)], mean_minutes=4.5, cv=0.35)


def _shipping():
    return StageConfig("shipping", [(0, 600, 5)], mean_minutes=2.5, cv=0.30)


def baseline_scenario() -> Scenario:
    return Scenario(
        name="baseline",
        label="Baseline labor plan",
        description=(
            "Conventional plan: 10 pickers on a flat 10-hour shift, manual "
            "pick-to-cart at 1.8 min/line."
        ),
        stages={
            "receiving": _receiving(),
            "picking": StageConfig(
                "picking", [(0, 600, 10)], per_line_minutes=1.8, cv=0.45
            ),
            "packing": _packing(),
            "shipping": _shipping(),
        },
    )


def amr_scenario() -> Scenario:
    return Scenario(
        name="amr_automation",
        label="AMR-assisted picking (automation)",
        description=(
            "Autonomous mobile robots bring goods to stationary pickers: "
            "pick time falls to 1.08 min/line (-40%) and the picking crew "
            "shrinks from 10 to 7."
        ),
        stages={
            "receiving": _receiving(),
            "picking": StageConfig(
                "picking", [(0, 600, 7)], per_line_minutes=1.08, cv=0.40
            ),
            "packing": _packing(),
            "shipping": _shipping(),
        },
    )


def shift_policy_scenario() -> Scenario:
    # Same total picker labor-hours as baseline (10 x 600 = 6,000 staff-min):
    # 7 x 150 + 13 x 300 + 7 x 150 = 6,000.
    picking_schedule = [(0, 150, 7), (150, 450, 13), (450, 600, 7)]
    return Scenario(
        name="shift_policy",
        label="Peak-aligned shift (shift policy)",
        description=(
            "Same picker labor-hours as baseline, re-timed: 7 pickers in "
            "the early morning, a 13-picker surge 10:30-15:30 across the "
            "demand peak, then 7 through close."
        ),
        stages={
            "receiving": _receiving(),
            "picking": StageConfig(
                "picking", picking_schedule, per_line_minutes=1.8, cv=0.45
            ),
            "packing": _packing(),
            "shipping": _shipping(),
        },
    )


def all_scenarios():
    return [baseline_scenario(), amr_scenario(), shift_policy_scenario()]
