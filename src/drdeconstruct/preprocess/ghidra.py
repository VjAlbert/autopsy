"""Integrazione con Ghidra in modalità headless.

Dato un file binario (ELF, PE, firmware grezzo con processore indicato),
lancia `analyzeHeadless`, decompila le funzioni ed esporta lo pseudocodice C,
pronto per il modulo Software. Ghidra va installato a parte (gratuito, serve
Java 21) e indicato con la variabile GHIDRA_INSTALL_DIR o con --ghidra.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from drdeconstruct.config import NO_WINDOW
from drdeconstruct.core.errors import DrDeconstructError

Runner = Callable[..., subprocess.CompletedProcess]

SCRIPTS_DIR = Path(__file__).parent / "ghidra_scripts"
EXPORT_SCRIPT = "ExportDecompiled.java"


@dataclass(frozen=True)
class DecompiledFunction:
    name: str
    entry: str
    size: int
    code: str


@dataclass(frozen=True)
class DecompiledProgram:
    program: str
    language: str
    functions: list[DecompiledFunction]

    def as_c_source(self) -> str:
        """Tutte le funzioni in un unico sorgente, con l'indirizzo come commento."""
        parts = [f"/* {self.program} ({self.language}) */"]
        for f in self.functions:
            parts.append(f"/* {f.name} @ {f.entry}, {f.size} byte */\n{f.code.strip()}")
        return "\n\n".join(parts) + "\n"

    @property
    def arch(self) -> str:
        # Es. "MIPS:LE:32:default" -> "MIPS:LE:32"
        return ":".join(self.language.split(":")[:3])


def find_analyze_headless(install_dir: str | os.PathLike | None = None) -> Path:
    """Trova lo script analyzeHeadless dentro l'installazione di Ghidra."""
    base = install_dir or os.environ.get("GHIDRA_INSTALL_DIR")
    if not base:
        raise DrDeconstructError(
            "Ghidra non configurato: installa Ghidra e imposta GHIDRA_INSTALL_DIR "
            "(o passa --ghidra con la cartella di installazione)."
        )
    name = "analyzeHeadless.bat" if sys.platform == "win32" else "analyzeHeadless"
    path = Path(base) / "support" / name
    if not path.exists():
        raise DrDeconstructError(f"analyzeHeadless non trovato in {path.parent}.")
    return path


class GhidraExporter:
    def __init__(
        self,
        install_dir: str | os.PathLike | None = None,
        timeout: float = 3600,
        runner: Runner = subprocess.run,
        headless: Path | None = None,
    ):
        self._install_dir = install_dir
        self._headless = headless
        self.timeout = timeout
        self._run = runner

    def command(
        self,
        binary: Path,
        project_dir: Path,
        output: Path,
        min_size: int,
        max_functions: int,
        processor: str | None,
        base_address: str | None,
    ) -> list[str]:
        headless = self._headless or find_analyze_headless(self._install_dir)
        cmd = [
            str(headless),
            str(project_dir),
            "drdec",
            "-import",
            str(binary),
            "-scriptPath",
            str(SCRIPTS_DIR),
            "-postScript",
            EXPORT_SCRIPT,
            str(output),
            str(min_size),
            str(max_functions),
            "-deleteProject",
        ]
        if processor:
            # Necessario per i firmware grezzi senza header (es. "MIPS:LE:32:default").
            cmd += ["-processor", processor]
        if base_address:
            cmd += ["-loader", "BinaryLoader", "-loader-baseAddr", base_address]
        return cmd

    def export(
        self,
        binary: str | os.PathLike,
        min_size: int = 16,
        max_functions: int = 500,
        processor: str | None = None,
        base_address: str | None = None,
        name_filter: str | None = None,
    ) -> DecompiledProgram:
        binary = Path(binary)
        if not binary.is_file():
            raise DrDeconstructError(f"File non trovato: {binary}")

        with tempfile.TemporaryDirectory(prefix="drdec_ghidra_") as tmp:
            tmp_path = Path(tmp)
            output = tmp_path / "export.json"
            cmd = self.command(
                binary, tmp_path, output, min_size, max_functions, processor, base_address
            )
            try:
                proc = self._run(
                    cmd, capture_output=True, text=True, timeout=self.timeout, **NO_WINDOW
                )
            except FileNotFoundError as exc:
                raise DrDeconstructError(f"Impossibile avviare Ghidra: {exc}") from exc
            except subprocess.TimeoutExpired as exc:
                raise DrDeconstructError(
                    f"Ghidra non ha finito entro {self.timeout:.0f}s: prova --max più basso."
                ) from exc

            if not output.exists():
                tail = "\n".join((proc.stdout or "").splitlines()[-15:])
                raise DrDeconstructError(
                    "Ghidra non ha prodotto l'export. Se è un firmware grezzo indica "
                    f"--processor. Ultime righe del log:\n{tail}\n{proc.stderr or ''}"
                )
            data = json.loads(output.read_text(encoding="utf-8"))

        functions = [DecompiledFunction(**f) for f in data.get("functions", [])]
        if name_filter:
            pattern = re.compile(name_filter)
            functions = [f for f in functions if pattern.search(f.name)]
        return DecompiledProgram(
            program=data.get("program", binary.name),
            language=data.get("language", "unknown"),
            functions=functions,
        )
