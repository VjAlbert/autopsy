"""Configurazione da variabili d'ambiente (nessun segreto nel codice)."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

BACKENDS = ("claude-code", "ollama", "api")

# Su Windows l'app grafica non ha console: senza questo flag ogni programma esterno
# (claude, Ghidra, flashrom, cargo) aprirebbe una finestra nera per qualche istante.
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


@dataclass(frozen=True)
class Settings:
    backend: str = "claude-code"
    model: str | None = None
    ollama_host: str = "http://localhost:11434"
    # Modello di riserva quando quello principale rifiuta (es. filtro "cyber"
    # su firmware o codice disassemblato). Vuoto = nessun secondo tentativo.
    fallback_model: str | None = "claude-opus-4-8"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            backend=os.environ.get("DRDEC_BACKEND", "claude-code"),
            model=os.environ.get("DRDEC_MODEL") or None,
            ollama_host=os.environ.get("DRDEC_OLLAMA_HOST", "http://localhost:11434"),
            fallback_model=os.environ.get("DRDEC_FALLBACK_MODEL", "claude-opus-4-8") or None,
        )
