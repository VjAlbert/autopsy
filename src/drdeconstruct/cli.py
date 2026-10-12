"""Riga di comando: `drdec analyze <file> --kind pseudocode_c`."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from drdeconstruct.config import BACKENDS, Settings
from drdeconstruct.core.errors import DrDeconstructError
from drdeconstruct.core.orchestrator import Orchestrator
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind, Domain
from drdeconstruct.hardware.analyzer import HardwareAnalyzer
from drdeconstruct.llm.factory import make_backend
from drdeconstruct.preprocess.chunker import split_c_functions
from drdeconstruct.software.analyzer import SoftwareAnalyzer


def build_orchestrator(settings: Settings) -> Orchestrator:
    llm = make_backend(settings)
    return Orchestrator(
        {Domain.SOFTWARE: SoftwareAnalyzer(llm), Domain.HARDWARE: HardwareAnalyzer(llm)}
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="drdec", description="Reverse engineering assistito da AI.")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="Analizza un file di testo (pseudocodice, ASM, log, dump).")
    a.add_argument("file", type=Path)
    a.add_argument("--domain", choices=[d.value for d in Domain])
    a.add_argument("--kind", choices=[k.value for k in ArtifactKind])
    a.add_argument("--arch", help="Architettura, es. mips32el, armv7, x86")
    a.add_argument("--context", default="", help="Cosa sai già del target")
    a.add_argument("--backend", choices=BACKENDS, help="Motore LLM (default da DRDEC_BACKEND)")
    a.add_argument("--model")
    a.add_argument("--split", action="store_true", help="Analizza ogni funzione C separatamente")
    a.add_argument("-o", "--output", type=Path, help="Salva il risultato JSON qui")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings.from_env()
    if args.backend:
        settings = replace(settings, backend=args.backend)
    if args.model:
        settings = replace(settings, model=args.model)

    try:
        content = args.file.read_text(encoding="utf-8", errors="replace")
        orch = build_orchestrator(settings)
        base = AnalysisRequest(
            content=content,
            domain=Domain(args.domain) if args.domain else None,
            kind=ArtifactKind(args.kind) if args.kind else None,
            arch=args.arch,
            context=args.context,
            source_name=args.file.name,
        )
        if args.split:
            chunks = split_c_functions(content)
            if not chunks:
                raise DrDeconstructError("Nessuna funzione C trovata da dividere.")
            results = {}
            for chunk in chunks:
                print(f"[*] {chunk.name}", file=sys.stderr)
                req = replace(base, content=chunk.code, kind=base.kind or ArtifactKind.PSEUDOCODE_C)
                results[chunk.name] = orch.run(req).model_dump()
            output = json.dumps(results, indent=2, ensure_ascii=False)
        else:
            output = orch.run(base).model_dump_json(indent=2)
    except (DrDeconstructError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
