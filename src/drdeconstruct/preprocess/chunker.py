"""Divide l'export di Ghidra/IDA in funzioni, da analizzare una alla volta."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Riga di firma C: tipo + nome + '(' ... ')' senza ';' finale.
_SIGNATURE = re.compile(r"^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^;]*\)\s*\{?\s*$")


@dataclass(frozen=True)
class FunctionChunk:
    name: str
    code: str


def split_c_functions(source: str) -> list[FunctionChunk]:
    """Separa le funzioni contando le graffe a partire da ogni firma."""
    lines = source.splitlines()
    chunks: list[FunctionChunk] = []
    i = 0
    while i < len(lines):
        match = _SIGNATURE.match(lines[i])
        if not match or lines[i].lstrip().startswith(("if", "for", "while", "switch", "return")):
            i += 1
            continue
        start, depth, opened = i, 0, False
        j = i
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            opened = opened or "{" in lines[j]
            if opened and depth <= 0:
                break
            j += 1
        if not opened:
            i += 1
            continue
        chunks.append(FunctionChunk(match.group(1), "\n".join(lines[start : j + 1])))
        i = j + 1
    return chunks
