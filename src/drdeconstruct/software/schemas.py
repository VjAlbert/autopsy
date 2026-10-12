"""Output strutturato del modulo Software."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RenamedSymbol(BaseModel):
    original: str
    proposed: str
    kind: Literal["variable", "parameter", "function", "global", "field", "type"]
    rationale: str
    confidence: Literal["high", "medium", "low"]


class SoftwareAnalysis(BaseModel):
    function_purpose: str = Field(description="Cosa fa la funzione, in una o due frasi.")
    control_flow: list[str] = Field(description="Passi principali del flusso di controllo.")
    renames: list[RenamedSymbol]
    rewritten_code: str = Field(
        description="Stesso codice con nomi semantici e commenti; semantica invariata."
    )
    algorithm_notes: str = Field(description="Algoritmi o strutture note riconosciute.")
    open_questions: list[str] = Field(description="Ciò che non si può dedurre dal solo frammento.")
