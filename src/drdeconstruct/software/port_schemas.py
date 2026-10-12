"""Output strutturato del porting di codice sorgente in un altro linguaggio.

A differenza dello scheletro (che parte da un decompilato e lascia i corpi da
scrivere), qui l'input è il codice sorgente dell'utente e il modello traduce
anche i corpi. Ogni pezzo tradotto porta con sé la sua checklist: i punti in
cui la traduzione è incerta e va controllata o testata.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]
Severity = Literal["high", "medium", "low"]
CheckKind = Literal[
    "behavior",
    "types",
    "ownership",
    "errors",
    "concurrency",
    "dependency",
    "performance",
    "unsafe",
    "test",
    "other",
]


class CheckItem(BaseModel):
    kind: CheckKind = Field(description="Area del controllo.")
    severity: Severity = Field(
        description="high = può cambiare il comportamento; low = solo da rileggere."
    )
    text: str = Field(description="Cosa controllare o testare, in una frase, in italiano.")


class PortedUnit(BaseModel):
    original_name: str = Field(description="Nome nel sorgente originale.")
    name: str = Field(description="Nome principale nel linguaggio di destinazione.")
    code: str = Field(
        description=(
            "Codice completo nel linguaggio di destinazione, con i corpi implementati. "
            "Senza import/use: vanno in 'imports'."
        )
    )
    imports: list[str] = Field(
        default_factory=list,
        description="Righe di import, una per voce (es. 'use std::collections::HashMap;').",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description=(
            "Librerie esterne necessarie, nel formato del gestore di pacchetti "
            "(Rust: 'regex = \"1\"'; Python: 'requests')."
        ),
    )
    confidence: Confidence
    checklist: list[CheckItem] = Field(
        default_factory=list,
        description="Punti incerti: tipi, ownership, gestione errori, comportamento, test.",
    )
    notes: str = Field(default="", description="Scelte di traduzione da sapere, in italiano.")


class SourceUnitInfo(BaseModel):
    """Da dove viene un pezzo tradotto (per checklist e anteprima)."""

    file: str
    name: str
    kind: Literal["function", "definitions", "file"]
    lines: tuple[int, int] | None = None


class PortFile(BaseModel):
    """Un file sorgente tradotto: i suoi pezzi nell'ordine originale."""

    source: str = Field(description="Percorso relativo del file originale.")
    module: str = Field(description="Nome del modulo/file generato.")
    source_language: str
    units: list[PortedUnit] = Field(default_factory=list)
    origins: list[SourceUnitInfo] = Field(default_factory=list)
    failed: dict[str, str] = Field(
        default_factory=dict, description="Pezzi non tradotti: nome -> errore."
    )


class CompileIssue(BaseModel):
    file: str
    line: int
    message: str
    unit: str | None = Field(default=None, description="Pezzo in cui cade l'errore, se noto.")


class PortProject(BaseModel):
    """Il risultato completo del porting."""

    name: str
    language: Literal["c", "python", "rust"]
    files: list[PortFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    compiler: str | None = Field(
        default=None, description="Controllo usato (es. 'cargo check'), o None se saltato."
    )
    compile_ok: bool | None = None
    compile_issues: list[CompileIssue] = Field(default_factory=list)
    fixed_units: list[str] = Field(
        default_factory=list, description="Pezzi corretti dopo gli errori del compilatore."
    )
