from __future__ import annotations

from collections.abc import Mapping, Sequence

from kairo_harness.config import ModelConfig
from kairo_harness.domain import ToolSpec
from kairo_harness.errors import ConfigError
from kairo_harness.providers.anthropic import AnthropicProvider
from kairo_harness.providers.base import ModelProvider
from kairo_harness.providers.gemini import GeminiProvider
from kairo_harness.providers.ollama import OllamaProvider
from kairo_harness.providers.openai import OpenAIProvider
from kairo_harness.providers.settings import ProviderSettings


class ProviderRegistry:
    def __init__(self, providers: Mapping[str, ModelProvider]) -> None:
        self._providers: dict[str, ModelProvider] = {}
        for name, provider in providers.items():
            if provider.name != name:
                raise ConfigError(
                    "Provider name does not match registry key",
                    code="provider.invalid_registration",
                    details={"configured": name, "provided": provider.name},
                )
            self._providers[name] = provider

    @classmethod
    def from_settings(cls, settings: ProviderSettings) -> ProviderRegistry:
        providers: dict[str, ModelProvider] = {}
        if settings.gemini is not None:
            providers["gemini"] = GeminiProvider(settings.gemini)
        if settings.anthropic is not None:
            providers["anthropic"] = AnthropicProvider(settings.anthropic)
        if settings.openai is not None:
            providers["openai"] = OpenAIProvider(settings.openai)
        if settings.ollama is not None:
            providers["ollama"] = OllamaProvider(settings.ollama)
        return cls(providers)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def get(self, name: str) -> ModelProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise ConfigError(
                "Provider is not configured",
                code="provider.not_configured",
                details={"provider": name},
            )
        return provider

    def select(
        self,
        config: ModelConfig,
        *,
        tools: Sequence[ToolSpec] = (),
    ) -> ModelProvider:
        provider = self.get(config.provider)
        provider.require_capabilities(
            config.model,
            streaming=config.stream_responses,
            tool_calls=bool(tools),
        )
        return provider

    async def aclose(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "aclose", None)
            if close is None:
                continue
            result = close()
            if hasattr(result, "__await__"):
                await result
