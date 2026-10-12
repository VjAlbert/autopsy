"""Output strutturato della generazione di scheletri di codice.

Il modello non restituisce codice finito ma un *piano*: firma ricostruita,
tipi, costanti e passi del flusso descritti a parole. Il codice viene poi
generato in modo deterministico da `software.scaffold`, così lo scheletro
resta un punto di partenza da completare e non una trascrizione del
programma originale.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]


class Parameter(BaseModel):
    name: str = Field(description="Nome semantico del parametro.")
    type: str = Field(description="Tipo nel linguaggio di destinazione.")
    description: str = ""


class StructField(BaseModel):
    name: str
    type: str = Field(description="Tipo nel linguaggio di destinazione.")
    offset: int | None = Field(default=None, description="Offset in byte, se dedotto.")
    description: str = ""


class StructDef(BaseModel):
    name: str = Field(description="Nome del tipo (CamelCase per Python/Rust).")
    description: str = ""
    fields: list[StructField] = Field(default_factory=list)


class Constant(BaseModel):
    name: str = Field(description="Nome in MAIUSCOLO_CON_UNDERSCORE.")
    value: str | None = Field(
        default=None,
        description="Valore numerico letterale (es. 0xEDB88320) o null se va estratto dal binario.",
    )
    description: str = ""


class FlowStep(BaseModel):
    kind: Literal["init", "check", "branch", "loop", "call", "compute", "io", "return", "other"]
    description: str = Field(description="Cosa fa il passo, a parole, una riga.")
    todo: str | None = Field(
        default=None, description="Cosa deve completare chi riscrive, se il passo non è ovvio."
    )


class FunctionSkeleton(BaseModel):
    original_name: str = Field(description="Nome nel decompilato (es. FUN_00401a20).")
    entry: str | None = Field(default=None, description="Indirizzo; lo compila il programma.")
    name: str = Field(description="Nome semantico proposto, in snake_case.")
    confidence: Confidence
    summary: str = Field(description="Cosa fa la funzione, una o due frasi (docstring).")
    parameters: list[Parameter] = Field(default_factory=list)
    return_type: str = Field(description="Tipo di ritorno nel linguaggio di destinazione.")
    return_description: str = ""
    steps: list[FlowStep] = Field(description="Struttura del flusso, nell'ordine.")
    structs: list[StructDef] = Field(
        default_factory=list, description="Strutture dati dedotte dagli accessi a offset."
    )
    constants: list[Constant] = Field(
        default_factory=list, description="Numeri magici e tabelle con un nome."
    )
    calls: list[str] = Field(
        default_factory=list, description="Funzioni chiamate (nomi come compaiono nel codice)."
    )
    open_questions: list[str] = Field(default_factory=list)


class ScaffoldModule(BaseModel):
    """Insieme delle funzioni di un sorgente, con nomi già resi coerenti tra loro."""

    name: str = Field(description="Nome base dei file generati.")
    language: Literal["c", "python", "rust"]
    source: str | None = None
    arch: str | None = None
    functions: list[FunctionSkeleton] = Field(default_factory=list)
    failed: dict[str, str] = Field(
        default_factory=dict, description="Funzioni non elaborate: nome originale -> errore."
    )
    notes: list[str] = Field(default_factory=list)
