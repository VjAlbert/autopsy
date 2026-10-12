"""Motore Ollama: modello locale, offline e gratuito.

Usa l'API REST di Ollama con output strutturato (`format` = JSON Schema).
Qualità sul reverse engineering inferiore a Claude.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from drdeconstruct.core.errors import BackendError
from drdeconstruct.llm.base import T, parse_json_into

Opener = Callable[..., object]


class OllamaBackend:
    name = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5-coder:14b",
        host: str = "http://localhost:11434",
        timeout: float = 900,
        opener: Opener = urllib.request.urlopen,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._open = opener

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        body = {
            "model": self.model,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._open(req, timeout=self.timeout) as resp:  # type: ignore[attr-defined]
                payload = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise BackendError(
                f"Ollama non raggiungibile su {self.host}: avvialo con `ollama serve` "
                f"e scarica il modello con `ollama pull {self.model}`."
            ) from exc
        return parse_json_into(payload.get("message", {}).get("content", ""), schema)
