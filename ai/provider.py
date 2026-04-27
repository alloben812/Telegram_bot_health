from __future__ import annotations

"""
Abstract AI provider interface.

Any concrete provider (OpenAI, Anthropic, local LLM, mock) must implement
AIProvider.  The rest of the codebase depends only on this interface.
"""

from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Minimal interface for a chat-completion style AI provider."""

    @abstractmethod
    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
    ) -> str:
        """
        Send a system + user message pair and return the assistant's reply.

        Args:
            system:     System/instruction message.
            user:       User message with the actual request.
            max_tokens: Upper bound on response length.

        Returns:
            Plain-text reply from the model.

        Raises:
            RuntimeError: if the provider is not configured (missing API key).
        """
