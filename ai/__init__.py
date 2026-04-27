from __future__ import annotations

"""
AI provider module.

Usage:
    from ai import get_provider
    provider = get_provider()           # returns default (OpenAI)
    reply = await provider.complete(system=..., user=..., max_tokens=800)
"""

from ai.provider import AIProvider
from ai.openai_provider import OpenAIProvider
from ai.schemas import DailyRecommendation, PlannedWorkout, WorkoutBlock

_default: AIProvider | None = None


def get_provider() -> AIProvider:
    """Return the configured default AI provider (singleton)."""
    global _default
    if _default is None:
        _default = OpenAIProvider()
    return _default


def set_provider(provider: AIProvider) -> None:
    """Override the default provider (useful for tests with mocks)."""
    global _default
    _default = provider


__all__ = [
    "AIProvider", "OpenAIProvider", "get_provider", "set_provider",
    "DailyRecommendation", "PlannedWorkout", "WorkoutBlock",
]
