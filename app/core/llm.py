from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    """Future LLM boundary used by feature services.

    Stage 1 does not call an LLM yet. Keeping the interface here prevents future
    Telegram handlers or feature code from depending on a concrete provider.
    """

    async def classify_intent(self, text: str) -> dict:
        ...

    async def generate_quiz(self, topic: str, materials: str, question_count: int) -> dict:
        ...

    async def grade_open_answer(self, question: str, answer: str, materials: str) -> dict:
        ...

