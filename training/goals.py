from __future__ import annotations

"""MVP goal presets.

Hard-coded for MVP. Replace with configurable DB-backed goals later.
"""

from typing import Literal, Optional
from dataclasses import dataclass


GoalType = Literal["race_time", "finish"]
Sport = Literal["run"]


@dataclass(frozen=True)
class GoalPreset:
    key: str
    label: str
    goal_type: GoalType
    sport: Sport
    distance_km: float
    target_time_minutes: Optional[int]  # None for "finish" goals


GOAL_PRESETS: dict[str, GoalPreset] = {
    "run_10k_60": GoalPreset(
        key="run_10k_60",
        label="10 км за 60 минут",
        goal_type="race_time",
        sport="run",
        distance_km=10.0,
        target_time_minutes=60,
    ),
    "run_half_220": GoalPreset(
        key="run_half_220",
        label="Полумарафон за 2:20",
        goal_type="race_time",
        sport="run",
        distance_km=21.1,
        target_time_minutes=140,
    ),
    "run_marathon_finish": GoalPreset(
        key="run_marathon_finish",
        label="Марафон — финишировать без остановок",
        goal_type="finish",
        sport="run",
        distance_km=42.2,
        target_time_minutes=None,
    ),
}


def get_preset(key: str) -> Optional[GoalPreset]:
    return GOAL_PRESETS.get(key)
