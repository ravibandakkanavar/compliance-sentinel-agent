"""Structured calls to Claude through the Anthropic SDK."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from sentinel.config import Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMRefusal(Exception):
    """The model declined the request; the caller decides whether to skip or abort."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    calls: int = 0


class LLM(Protocol):
    usage: Usage

    def parse(self, system: str, context: str, task: str, schema: type[T]) -> T:
        """Return a validated `schema` instance.

        `system` and `context` form the stable prefix and are cached; `task`
        is the part that varies between calls.
        """
        ...


class ClaudeLLM:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()
        self._model = settings.model
        self._effort = settings.effort
        self._fallbacks = settings.enable_fallbacks
        self.usage = Usage()

    def parse(self, system: str, context: str, task: str, schema: type[T]) -> T:
        content: list[dict] = []
        if context:
            # The breakpoint sits after the context so repeated calls over the
            # same repository or regulation text read it from the cache.
            content.append(
                {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}}
            )
        content.append({"type": "text", "text": task})

        request = {
            "model": self._model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": self._effort},
            "output_format": schema,
        }
        if self._fallbacks:
            response = self._client.beta.messages.parse(
                betas=[FALLBACK_BETA], fallbacks="default", **request
            )
        else:
            response = self._client.messages.parse(**request)

        self.usage.calls += 1
        self.usage.input_tokens += response.usage.input_tokens
        self.usage.output_tokens += response.usage.output_tokens
        self.usage.cache_read_tokens += response.usage.cache_read_input_tokens or 0

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMRefusal(f"model declined the request (category: {category})")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise RuntimeError(f"model returned no parsed output (stop: {response.stop_reason})")
        return response.parsed_output
