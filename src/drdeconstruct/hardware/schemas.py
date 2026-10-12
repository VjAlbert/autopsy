"""Output strutturato del modulo Hardware (analisi di dati già acquisiti)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DecodedField(BaseModel):
    offset_or_position: str
    raw: str
    meaning: str
    confidence: Literal["high", "medium", "low"]


class HardwareAnalysis(BaseModel):
    summary: str = Field(description="Cosa rappresentano i dati, in breve.")
    protocol_or_format: str = Field(description="Protocollo o formato riconosciuto, se noto.")
    decoded_fields: list[DecodedField]
    structures: list[str] = Field(description="Tabelle, header o strutture individuate.")
    pin_or_register_notes: list[str] = Field(
        description="Ipotesi su pin, registri o periferiche coinvolte."
    )
    open_questions: list[str]
