"""Motore opzionale via chiave API Anthropic (spento di default).

Richiede `pip install drdeconstruct[api]` e la variabile ANTHROPIC_API_KEY.
"""

from __future__ import annotations

from drdeconstruct.core.errors import BackendError, RefusalError
from drdeconstruct.llm.base import T

FALLBACK_BETA = "server-side-fallback-2026-07-01"


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
        self.last_model: str | None = None

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        # `fallbacks: "default"`: se il modello rifiuta (es. filtro "cyber" su
        # firmware o codice disassemblato) il server riprova da solo su un modello
        # scelto in base alla categoria del rifiuto, nella stessa chiamata.
        resp = self._client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
            output_format=schema,
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        self.last_usage = resp.usage
        self.last_model = resp.model
        if resp.stop_reason == "refusal":
            details = resp.stop_details
            category = getattr(details, "category", None) if details else None
            raise RefusalError(
                f"Rifiutata (categoria: {category or 'n/d'}) anche dopo il fallback."
            )
        if resp.stop_reason == "max_tokens":
            raise BackendError("Output troncato: dividi l'input in parti più piccole.")
        return resp.parsed_output
