"""Crea il motore LLM scelto dall'utente."""

from __future__ import annotations

from drdeconstruct.config import Settings
from drdeconstruct.core.errors import BackendError
from drdeconstruct.llm.base import LLMBackend


def make_backend(settings: Settings) -> LLMBackend:
    if settings.backend == "claude-code":
        from drdeconstruct.llm.claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend(model=settings.model, fallback_model=settings.fallback_model)
    if settings.backend == "ollama":
        from drdeconstruct.llm.ollama import OllamaBackend

        return OllamaBackend(model=settings.model or "qwen2.5-coder:14b", host=settings.ollama_host)
    if settings.backend == "api":
        from drdeconstruct.llm.anthropic_api import AnthropicAPIBackend

        return AnthropicAPIBackend(model=settings.model or "claude-opus-5-5")
    raise BackendError(f"Motore sconosciuto: {settings.backend}")
