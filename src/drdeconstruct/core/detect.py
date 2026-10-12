"""Euristica di fallback per indovinare il tipo di input.

Usata SOLO se l'operatore non dichiara dominio e tipo. Un file binario può
essere sia firmware da disassemblare sia un dump grezzo: sotto la soglia di
confidenza l'orchestratore si ferma e chiede all'operatore.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from drdeconstruct.core.types import ArtifactKind

_C_HINTS = re.compile(
    r"\b(undefined[1248]?|FUN_[0-9a-fA-F]+|DAT_[0-9a-fA-F]+|uint|int|void|char|return)\b"
)
_ASM_HINTS = re.compile(
    r"^\s*(?:[0-9a-fA-F]{4,}[:\s]+)?(mov|push|pop|call|jmp|j[a-z]{1,3}|ldr|str|bl|bx|addiu|lw|sw|jal|lui)\b",
    re.IGNORECASE | re.MULTILINE,
)
_BUS_HINTS = re.compile(r"\b(uart|spi|i2c|can|tx|rx|miso|mosi|sda|scl|0x[0-9a-fA-F]{2})\b", re.I)
_REG_HINTS = re.compile(r"\b(reg|register|base|offset|0x[0-9a-fA-F]{8})\b", re.I)
_HEXDUMP = re.compile(r"^[0-9a-fA-F]{6,8}[:\s]+(?:[0-9a-fA-F]{2}\s+){8,}", re.MULTILINE)


@dataclass(frozen=True)
class Guess:
    kind: ArtifactKind
    confidence: float

    def __str__(self) -> str:
        return f"{self.kind.value} ({self.confidence:.0%})"


def guess(content: str, source_name: str | None = None) -> Guess:
    """Restituisce il tipo più probabile con una confidenza in [0, 1]."""
    lines = max(content.count("\n") + 1, 1)
    name = (source_name or "").lower()

    if name.endswith((".c", ".cpp", ".h")):
        return Guess(ArtifactKind.PSEUDOCODE_C, 0.9)
    if name.endswith((".s", ".asm")):
        return Guess(ArtifactKind.ASSEMBLY, 0.9)

    scores = {
        ArtifactKind.PSEUDOCODE_C: len(_C_HINTS.findall(content)) / lines
        + (0.5 if "{" in content and "}" in content else 0.0),
        ArtifactKind.ASSEMBLY: 2 * len(_ASM_HINTS.findall(content)) / lines,
        ArtifactKind.FLASH_DUMP: 2 * len(_HEXDUMP.findall(content)) / lines,
        ArtifactKind.BUS_LOG: len(_BUS_HINTS.findall(content)) / lines / 2,
        ArtifactKind.REGISTER_MAP: len(_REG_HINTS.findall(content)) / lines / 2,
    }
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values()) or 1.0
    return Guess(best, round(min(scores[best] / total, 1.0), 2))
