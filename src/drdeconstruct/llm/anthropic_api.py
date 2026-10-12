"""Motore opzionale via chiave API Anthropic (spento di default).

Richiede `pip install drdeconstruct[api]` e la variabile ANTHROPIC_API_KEY.
"""

from __future__ import annotations

from drdeconstruct.core.errors import BackendError, RefusalError
from drdeconstruct.llm.base import T


class AnthropicAPIBackend:
    name = "api"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium"):
        try:
            import anthropic
        except ImportError as exc:
            raise BackendError("Installa l'extra: pip install 'drdeconstruct[api]'") from exc
        self._client = anthropic.Anthropic()  # legge ANTHROPIC_API_KEY
        self.model = model
        self.effort = effort
        self.last_usage = None

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        resp = self._client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
            output_format=schema,
        )
        if resp.stop_reason == "refusal":
            raise RefusalError(str(resp.stop_details))
        if resp.stop_reason == "max_tokens":
            raise BackendError("Output troncato: dividi l'input in parti più piccole.")
        self.last_usage = resp.usage
        return resp.parsed_output
