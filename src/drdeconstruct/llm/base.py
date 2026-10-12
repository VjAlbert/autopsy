"""Interfaccia comune dei motori LLM.

Ogni motore riceve un prompt di sistema, un messaggio utente e uno schema
Pydantic, e restituisce un'istanza validata di quello schema. Gli
analizzatori dipendono solo da questa interfaccia, mai da un motore preciso.
"""

from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from drdeconstruct.core.errors import BackendError

T = TypeVar("T", bound=BaseModel)


class LLMBackend(Protocol):
    name: str

    def structured(self, system: str, user: str, schema: type[T]) -> T: ...


_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def parse_json_into(text: str, schema: type[T]) -> T:
    """Estrae un oggetto JSON dal testo del modello e lo valida contro lo schema.

    Accetta JSON puro, JSON dentro un blocco ``` o JSON circondato da testo.
    """
    candidates = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return schema.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
    raise BackendError(f"Output del modello non conforme a {schema.__name__}: {last_error}")


def schema_instructions(schema: type[BaseModel]) -> str:
    """Istruzioni da accodare al prompt per i motori senza output strutturato nativo."""
    return (
        "Rispondi SOLO con un oggetto JSON valido conforme a questo JSON Schema, "
        "senza testo prima o dopo:\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )
