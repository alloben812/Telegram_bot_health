from __future__ import annotations

"""
Pydantic schemas for structured AI output.

The AI must return JSON matching DailyRecommendation.
Backend validates before saving or displaying.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class WorkoutBlock(BaseModel):
    title: str
    duration_minutes: int
    target_hr_zone: Optional[str] = None
    target_hr_range: Optional[str] = None
    notes: Optional[str] = None


class PlannedWorkout(BaseModel):
    sport: Literal[
        "run", "bike", "swim", "strength",
        "walk", "mobility", "recovery", "rest", "other"
    ]
    title: str
    duration_minutes: Optional[int] = None
    intensity: Literal["z1", "z2", "z3", "z4", "z5", "easy", "moderate", "hard", "rest"]
    blocks: List[WorkoutBlock] = Field(default_factory=list)


class DailyRecommendation(BaseModel):
    readiness_score: int = Field(..., ge=0, le=100)
    status_label: str
    main_recommendation: str
    planned_workout: PlannedWorkout
    reasoning: List[str]
    avoid: List[str]
    control: List[str]
    confidence: Literal["low", "medium", "high"]
    data_gaps: List[str] = Field(default_factory=list)

    @field_validator("reasoning", "avoid", "control")
    @classmethod
    def non_empty_lists(cls, v: list) -> list:
        if not v:
            raise ValueError("must contain at least one item")
        return v
