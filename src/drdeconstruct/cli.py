"""Riga di comando: `drdec analyze` per i testi, `drdec decompile` per i binari,
`drdec web` per studiare il front-end di un sito."""

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
from drdeconstruct.web.analyzer import WebAnalyzer
from drdeconstruct.web.extract import build_snapshot
from drdeconstruct.web.fetcher import SiteFetcher
from drdeconstruct.web.mirror import mirror_page
from drdeconstruct.web.scaffold import write_scaffold


def build_orchestrator(settings: Settings) -> Orchestrator:
    llm = make_backend(settings)
    return Orchestrator(
        {
            Domain.SOFTWARE: SoftwareAnalyzer(llm),
            Domain.HARDWARE: HardwareAnalyzer(llm),
            Domain.WEB: WebAnalyzer(llm),
        }
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
    _add_engine_args(d)

    w = sub.add_parser(
        "web",
        help="Studia il front-end di un sito pubblico e genera uno scheletro da reinterpretare.",
        description=(
            "Scarica solo HTML, CSS e JS pubblici dello stesso sito, rispettando robots.txt; "
            "non aggira login né paywall. Lo scheletro non contiene testi, immagini o marchi "
            "del sito: è una base per la TUA versione, non una copia da ripubblicare."
        ),
    )
    w.add_argument("url")
    w.add_argument(
        "--snapshot-only", action="store_true", help="Solo mappa strutturale, senza modello"
    )
    w.add_argument("--scaffold", type=Path, metavar="CARTELLA", help="Scrivi qui lo scheletro")
    w.add_argument(
        "--mirror",
        type=Path,
        metavar="CARTELLA",
        help="Salva qui una copia privata della sola pagina, da aprire offline e modificare",
    )
    w.add_argument("--max-resources", type=int, default=20, help="Massimo CSS/JS da scaricare")
    _add_engine_args(w)
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


def run_web(url: str, settings: Settings | None, context: str = "", max_resources: int = 20):
    """Scarica, mappa e (se `settings` c'è) fa spiegare la pagina. Usato da CLI e GUI."""
    site = SiteFetcher(max_resources=max_resources).fetch(url)
    snapshot = build_snapshot(
        site.url,
        site.html,
        stylesheets=[r.text for r in site.stylesheets],
        scripts=[r.text for r in site.scripts],
        third_party_scripts=site.third_party_scripts,
        skipped=site.skipped,
    )
    if settings is None:
        return snapshot, None
    return snapshot, WebAnalyzer(make_backend(settings)).analyze_snapshot(snapshot, context)


def _cmd_web(args: argparse.Namespace) -> str:
    if args.mirror:
        result = mirror_page(args.url, args.mirror, progress=lambda m: print(m, file=sys.stderr))
        return (
            f"Copia privata salvata in {result.index} ({len(result.saved)} file, "
            f"{len(result.skipped)} saltati: vedi LEGGIMI.txt). Non ripubblicarla."
        )
    if args.snapshot_only and args.scaffold:
        raise DrDeconstructError("--scaffold richiede il modello: togli --snapshot-only.")
    print(f"[*] Raccolgo la struttura di {args.url}…", file=sys.stderr)
    settings = None if args.snapshot_only else _settings(args)
    snapshot, analysis = run_web(args.url, settings, args.context, args.max_resources)
    if analysis is None:
        return snapshot.model_dump_json(indent=2)
    if args.scaffold:
        for path in write_scaffold(analysis, args.scaffold, snapshot.css.breakpoints_px):
            print(f"[*] Scheletro: {path}", file=sys.stderr)
    return json.dumps(
        {"snapshot": snapshot.model_dump(), "analysis": analysis.model_dump()},
        indent=2,
        ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    commands = {"analyze": _cmd_analyze, "decompile": _cmd_decompile, "web": _cmd_web}
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
