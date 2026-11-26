from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from kairo_harness.providers.anthropic import AnthropicConfig
from kairo_harness.providers.gemini import GeminiConfig
from kairo_harness.providers.ollama import OllamaConfig
from kairo_harness.providers.openai import OpenAIConfig


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gemini: GeminiConfig | None = None
    anthropic: AnthropicConfig | None = None
    openai: OpenAIConfig | None = None
    ollama: OllamaConfig | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ProviderSettings:
        env = os.environ if environ is None else environ
        return cls(
            gemini=GeminiConfig.from_env(env),
            anthropic=AnthropicConfig.from_env(env),
            openai=OpenAIConfig.from_env(env),
            ollama=OllamaConfig.from_env(env),
        )
