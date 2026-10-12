"""Configurazione da variabili d'ambiente (nessun segreto nel codice)."""

from __future__ import annotations

import os
from dataclasses import dataclass

BACKENDS = ("claude-code", "ollama", "api")


@dataclass(frozen=True)
class Settings:
    backend: str = "claude-code"
    model: str | None = None
    ollama_host: str = "http://localhost:11434"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            backend=os.environ.get("DRDEC_BACKEND", "claude-code"),
            model=os.environ.get("DRDEC_MODEL") or None,
            ollama_host=os.environ.get("DRDEC_OLLAMA_HOST", "http://localhost:11434"),
        )
