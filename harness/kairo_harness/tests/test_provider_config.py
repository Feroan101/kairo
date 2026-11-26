import asyncio

import pytest
from kairo_harness.config import ModelConfig
from kairo_harness.domain import ModelCapabilities, ToolSpec
from kairo_harness.errors import ConfigError
from kairo_harness.providers.anthropic import AnthropicConfig
from kairo_harness.providers.gemini import GeminiConfig, GeminiProvider
from kairo_harness.providers.mock import MockProvider
from kairo_harness.providers.ollama import OllamaConfig
from kairo_harness.providers.openai import OpenAIConfig
from kairo_harness.providers.registry import ProviderRegistry
from kairo_harness.providers.settings import ProviderSettings
from support import make_tool


class LimitedProvider(MockProvider):
    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(streaming=False, tool_calls=False)


def test_provider_settings_from_env_reads_credentials_without_storing_them() -> None:
    environ = {
        "GEMINI_API_KEY": "gemini-secret",
        "ANTHROPIC_API_KEY": "anthropic-secret",
        "OPENAI_API_KEY": "openai-secret",
        "KAIRO_OLLAMA_BASE_URL": "http://localhost:11434",
    }

    settings = ProviderSettings.from_env(environ)
    dump = str(settings.model_dump())

    assert settings.gemini is not None
    assert settings.anthropic is not None
    assert settings.openai is not None
    assert settings.ollama is not None
    assert "gemini-secret" not in dump
    assert "anthropic-secret" not in dump
    assert "openai-secret" not in dump
    assert settings.gemini.api_key(environ) == "gemini-secret"
    assert settings.anthropic.api_key(environ) == "anthropic-secret"
    assert settings.openai.api_key(environ) == "openai-secret"


def test_provider_settings_honor_google_api_key_fallback_and_overrides() -> None:
    settings = ProviderSettings.from_env(
        {
            "GOOGLE_API_KEY": "google-secret",
            "KAIRO_GEMINI_API_KEY_ENV": "CUSTOM_GEMINI_KEY",
            "CUSTOM_GEMINI_KEY": "custom-secret",
            "KAIRO_ANTHROPIC_API_KEY_ENV": "CUSTOM_ANTHROPIC_KEY",
            "CUSTOM_ANTHROPIC_KEY": "anthropic-secret",
            "KAIRO_OPENAI_API_KEY_ENV": "CUSTOM_OPENAI_KEY",
            "CUSTOM_OPENAI_KEY": "openai-secret",
            "KAIRO_GEMINI_BASE_URL": "https://gemini.example.test",
            "KAIRO_ANTHROPIC_BASE_URL": "https://anthropic.example.test",
            "KAIRO_OPENAI_BASE_URL": "https://openai.example.test",
        }
    )

    assert settings.gemini is not None
    assert settings.gemini.api_key_env == "CUSTOM_GEMINI_KEY"
    assert settings.gemini.base_url is not None
    assert str(settings.gemini.base_url) == "https://gemini.example.test/"
    assert settings.anthropic is not None
    assert str(settings.anthropic.base_url) == "https://anthropic.example.test/"
    assert settings.openai is not None
    assert str(settings.openai.base_url) == "https://openai.example.test/"

    fallback = ProviderSettings.from_env({"GOOGLE_API_KEY": "google-secret"})
    assert fallback.gemini is not None
    assert fallback.gemini.api_key_env == "GOOGLE_API_KEY"


def test_registry_from_settings_registers_configured_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environ = {
        "GEMINI_API_KEY": "gemini-secret",
        "ANTHROPIC_API_KEY": "anthropic-secret",
        "OPENAI_API_KEY": "openai-secret",
    }
    settings = ProviderSettings.from_env(environ)
    for key, value in environ.items():
        monkeypatch.setenv(key, value)

    registry = ProviderRegistry.from_settings(settings)

    assert set(registry.names) == {"gemini", "anthropic", "openai"}
    asyncio.run(registry.aclose())


def test_registry_select_validates_provider_capabilities() -> None:
    provider = MockProvider()
    registry = ProviderRegistry({"mock": provider})
    config = ModelConfig(provider="mock", model="mock-model", stream_responses=True)
    tools: list[ToolSpec] = [make_tool()]

    assert registry.select(config, tools=tools) is provider

    limited = LimitedProvider()
    limited_registry = ProviderRegistry({"mock": limited})
    with pytest.raises(ConfigError) as error_info:
        limited_registry.select(config, tools=tools)
    assert error_info.value.code == "provider.capability_unsupported"
    assert error_info.value.details == {
        "provider": "mock",
        "model": "mock-model",
        "capabilities": "streaming,tool_calls",
    }


def test_registry_rejects_unknown_or_mismatched_providers() -> None:
    registry = ProviderRegistry({"mock": MockProvider()})

    with pytest.raises(ConfigError) as error_info:
        registry.get("missing")
    assert error_info.value.code == "provider.not_configured"

    with pytest.raises(ConfigError) as mismatch_info:
        ProviderRegistry({"other": MockProvider()})
    assert mismatch_info.value.code == "provider.invalid_registration"


def test_provider_env_defaults_and_activation_are_stable() -> None:
    assert ProviderSettings.from_env({}) == ProviderSettings()

    openai = OpenAIConfig.from_env({"OPENAI_API_KEY": "secret"})
    anthropic = AnthropicConfig.from_env({"ANTHROPIC_API_KEY": "secret"})
    gemini = GeminiConfig.from_env({"GOOGLE_API_KEY": "secret"})
    ollama = OllamaConfig.from_env({"KAIRO_OLLAMA_BASE_URL": "http://localhost:11434"})

    assert openai is not None
    assert openai.api_key_env == "OPENAI_API_KEY"
    assert openai.timeout_seconds == 30.0
    assert openai.max_retries == 2
    assert anthropic is not None
    assert anthropic.api_key_env == "ANTHROPIC_API_KEY"
    assert anthropic.timeout_seconds == 30.0
    assert anthropic.default_max_tokens == 1024
    assert gemini is not None
    assert gemini.api_key_env == "GOOGLE_API_KEY"
    assert gemini.timeout_seconds == 30.0
    assert ollama is not None
    assert ollama.timeout_seconds == 30.0

    assert (
        OpenAIConfig.from_env({"KAIRO_OPENAI_API_KEY_ENV": "", "OPENAI_API_KEY": "secret"}) is None
    )
    assert (
        AnthropicConfig.from_env({"KAIRO_ANTHROPIC_API_KEY_ENV": "", "ANTHROPIC_API_KEY": "secret"})
        is None
    )
    assert OpenAIConfig.from_env({"KAIRO_OPENAI_TIMEOUT_SECONDS": "12.5"}) is None
    assert AnthropicConfig.from_env({"KAIRO_ANTHROPIC_MAX_TOKENS": "2048"}) is None
    assert GeminiConfig.from_env({"KAIRO_GEMINI_TIMEOUT_SECONDS": "9"}) is None
    assert OllamaConfig.from_env({}) is None


def test_model_capability_overrides_are_explicit() -> None:
    config = GeminiConfig(
        model_capabilities={
            "gemini-legacy": ModelCapabilities(streaming=False, tool_calls=False),
        }
    )

    provider = GeminiProvider(config, client=object())

    assert provider.capabilities_for("gemini-2.5-flash") == ModelCapabilities(
        streaming=True, tool_calls=True
    )
    assert provider.capabilities_for("gemini-legacy") == ModelCapabilities()
