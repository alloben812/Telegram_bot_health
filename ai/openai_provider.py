from __future__ import annotations

"""
OpenAI implementation of AIProvider.

Default model is gpt-4o.  Override via OPENAI_MODEL env var.
"""

import openai

from ai.provider import AIProvider
from config import config


class OpenAIProvider(AIProvider):
    """Calls the OpenAI Chat Completions API."""

    def __init__(self) -> None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY не задан — добавь в .env и перезапусти бота."
            )
        self._client = openai.AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self._model = config.OPENAI_MODEL

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""
