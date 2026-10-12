"""Riga di comando: `drdec analyze` per i testi, `drdec decompile` per i binari."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from drdeconstruct.config import BACKENDS, Settings
from drdeconstruct.core.errors import BackendError, DrDeconstructError
from drdeconstruct.core.orchestrator import Orchestrator
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind, Domain
from drdeconstruct.hardware.analyzer import HardwareAnalyzer
from drdeconstruct.llm.factory import make_backend
from drdeconstruct.preprocess.chunker import split_c_functions
from drdeconstruct.preprocess.ghidra import GhidraExporter
from drdeconstruct.software.analyzer import SoftwareAnalyzer


def build_orchestrator(settings: Settings) -> Orchestrator:
    llm = make_backend(settings)
    return Orchestrator(
        {Domain.SOFTWARE: SoftwareAnalyzer(llm), Domain.HARDWARE: HardwareAnalyzer(llm)}
    )


def analyze_functions(
    orch: Orchestrator, base: AnalysisRequest, functions: list[tuple[str, str]]
) -> dict[str, dict]:
    """Analizza le funzioni una alla volta; un errore su una non ferma le altre."""
    results: dict[str, dict] = {}
    for i, (name, code) in enumerate(functions, 1):
        print(f"[{i}/{len(functions)}] {name}", file=sys.stderr)
        req = replace(base, content=code, kind=base.kind or ArtifactKind.PSEUDOCODE_C)
        try:
            results[name] = orch.run(req).model_dump()
        except BackendError as exc:
            print(f"    errore: {exc}", file=sys.stderr)
            results[name] = {"error": str(exc)}
    return results


def _add_engine_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--backend", choices=BACKENDS, help="Motore LLM (default da DRDEC_BACKEND)")
    p.add_argument("--model")
    p.add_argument("--context", default="", help="Cosa sai già del target")
    p.add_argument("-o", "--output", type=Path, help="Salva il risultato qui")


def _add_scaffold_lang(p: argparse.ArgumentParser) -> None:
    from drdeconstruct.software.scaffold import DEFAULT_LANGUAGE, LANGUAGES

    p.add_argument(
        "--lang",
        choices=LANGUAGES,
        default=DEFAULT_LANGUAGE.value,
        help="Linguaggio dello scheletro (default: c)",
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="drdec", description="Reverse engineering assistito da AI.")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="Analizza un file di testo (pseudocodice, ASM, log, dump).")
    a.add_argument("file", type=Path)
    a.add_argument("--domain", choices=[d.value for d in Domain])
    a.add_argument("--kind", choices=[k.value for k in ArtifactKind])
    a.add_argument("--arch", help="Architettura, es. mips32el, armv7, x86")
    a.add_argument("--split", action="store_true", help="Analizza ogni funzione C separatamente")
    _add_engine_args(a)

    s = sub.add_parser(
        "scaffold",
        help="Genera uno scheletro di codice riscritto da pseudocodice o assembly.",
        description=(
            "Ricostruisce firme, tipi, costanti e flusso delle funzioni e scrive un sorgente "
            "da completare, con TODO nei corpi. È un punto di partenza per reinterpretare "
            "software tuo o open source, non una copia del programma originale."
        ),
    )
    s.add_argument("file", type=Path)
    s.add_argument("--out", type=Path, required=True, metavar="CARTELLA", help="Dove scrivere")
    s.add_argument("--kind", choices=[ArtifactKind.PSEUDOCODE_C.value, ArtifactKind.ASSEMBLY.value])
    s.add_argument("--arch", help="Architettura, es. mips32el, armv7, x86")
    _add_scaffold_lang(s)
    _add_engine_args(s)

    d = sub.add_parser(
        "decompile", help="Decompila un binario con Ghidra e, a richiesta, analizza le funzioni."
    )
    d.add_argument("binary", type=Path)
    d.add_argument("--ghidra", help="Cartella di installazione di Ghidra (o GHIDRA_INSTALL_DIR)")
    d.add_argument("--processor", help="Per firmware grezzi, es. MIPS:LE:32:default o ARM:LE:32:v7")
    d.add_argument(
        "--base-address", help="Indirizzo di caricamento per firmware grezzi, es. 0x80000000"
    )
    d.add_argument("--min-size", type=int, default=16, help="Salta funzioni più piccole (byte)")
    d.add_argument("--max", type=int, default=500, dest="max_functions", help="Massimo funzioni")
    d.add_argument("--filter", help="Regex sul nome delle funzioni da tenere")
    d.add_argument(
        "--analyze",
        action="store_true",
        help="Manda ogni funzione al modello (altrimenti solo export C)",
    )
    d.add_argument(
        "--scaffold", type=Path, metavar="CARTELLA", help="Genera qui lo scheletro di codice"
    )
    _add_scaffold_lang(d)
    _add_engine_args(d)
    return p


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    if args.backend:
        settings = replace(settings, backend=args.backend)
    if args.model:
        settings = replace(settings, model=args.model)
    return settings


def _cmd_analyze(args: argparse.Namespace) -> str:
    content = args.file.read_text(encoding="utf-8", errors="replace")
    orch = build_orchestrator(_settings(args))
    base = AnalysisRequest(
        content=content,
        domain=Domain(args.domain) if args.domain else None,
        kind=ArtifactKind(args.kind) if args.kind else None,
        arch=args.arch,
        context=args.context,
        source_name=args.file.name,
    )
    if not args.split:
        return orch.run(base).model_dump_json(indent=2)
    chunks = split_c_functions(content)
    if not chunks:
        raise DrDeconstructError("Nessuna funzione C trovata da dividere.")
    results = analyze_functions(orch, base, [(c.name, c.code) for c in chunks])
    return json.dumps(results, indent=2, ensure_ascii=False)


def run_scaffold(
    settings: Settings,
    functions: list,
    out_dir: Path,
    language: str = "c",
    arch: str | None = None,
    context: str = "",
    source: str | None = None,
):
    """Genera e scrive lo scheletro di codice. Usato da CLI e GUI."""
    from drdeconstruct.software.scaffold import ScaffoldGenerator, write_scaffold

    out_dir = Path(out_dir)
    # Controllo prima di chiamare il modello, per non sprecare l'analisi.
    if out_dir.exists() and any(out_dir.iterdir()):
        raise DrDeconstructError(f"{out_dir} non è vuota: scegli una cartella vuota o nuova.")
    module = ScaffoldGenerator(make_backend(settings)).generate(
        functions,
        language,
        arch=arch,
        context=context,
        source=source,
        progress=lambda i, n, name: print(f"[{i}/{n}] scheletro {name}", file=sys.stderr),
    )
    if not module.functions:
        errors = "; ".join(f"{k}: {v}" for k, v in module.failed.items())
        raise DrDeconstructError(f"Nessuna funzione elaborata: {errors}")
    paths = write_scaffold(module, out_dir)
    return module, paths


def _cmd_scaffold(args: argparse.Namespace) -> str:
    from drdeconstruct.software.scaffold import SourceFunction

    content = args.file.read_text(encoding="utf-8", errors="replace")
    chunks = [] if args.kind == ArtifactKind.ASSEMBLY.value else split_c_functions(content)
    functions = [SourceFunction(c.name, c.code) for c in chunks] or [
        SourceFunction(args.file.stem, content)
    ]
    module, paths = run_scaffold(
        _settings(args), functions, args.out, args.lang, args.arch, args.context, args.file.name
    )
    for path in paths:
        print(f"[*] Scheletro: {path}", file=sys.stderr)
    return module.model_dump_json(indent=2)


def _cmd_decompile(args: argparse.Namespace) -> str:
    print(f"[*] Ghidra sta analizzando {args.binary.name}…", file=sys.stderr)
    program = GhidraExporter(install_dir=args.ghidra).export(
        args.binary,
        min_size=args.min_size,
        max_functions=args.max_functions,
        processor=args.processor,
        base_address=args.base_address,
        name_filter=args.filter,
    )
    print(f"[*] {len(program.functions)} funzioni ({program.language})", file=sys.stderr)
    if args.scaffold:
        from drdeconstruct.software.scaffold import SourceFunction

        functions = [SourceFunction(f.name, f.code, f.entry) for f in program.functions]
        _, paths = run_scaffold(
            _settings(args),
            functions,
            args.scaffold,
            args.lang,
            program.arch,
            args.context,
            program.program,
        )
        for path in paths:
            print(f"[*] Scheletro: {path}", file=sys.stderr)
    if not args.analyze:
        return program.as_c_source()

    orch = build_orchestrator(_settings(args))
    base = AnalysisRequest(
        content="",
        kind=ArtifactKind.PSEUDOCODE_C,
        arch=program.arch,
        context=args.context,
        source_name=args.binary.name,
    )
    results = analyze_functions(
        orch, base, [(f"{f.name}@{f.entry}", f.code) for f in program.functions]
    )
    return json.dumps(
        {"program": program.program, "language": program.language, "functions": results},
        indent=2,
        ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    commands = {"analyze": _cmd_analyze, "scaffold": _cmd_scaffold, "decompile": _cmd_decompile}
    try:
        output = commands[args.command](args)
    except (DrDeconstructError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"[*] Salvato in {args.output}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
