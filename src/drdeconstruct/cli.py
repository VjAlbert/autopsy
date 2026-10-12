"""Riga di comando: `drdec analyze` per i testi, `drdec decompile` per i binari,
`drdec port` per tradurre il proprio codice sorgente in Rust (o altro),
`drdec web` per studiare il front-end di un sito,
`drdec home` per i dispositivi smart home (Xiaomi, Aqara, Tapo)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from drdeconstruct.config import BACKENDS, Settings
from drdeconstruct.core.errors import BackendError, DrDeconstructError, RefusalError
from drdeconstruct.core.orchestrator import Orchestrator
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind, Domain
from drdeconstruct.hardware.analyzer import HardwareAnalyzer
from drdeconstruct.llm.base import LLMBackend
from drdeconstruct.llm.factory import make_backend
from drdeconstruct.preprocess.chunker import split_c_functions
from drdeconstruct.preprocess.ghidra import GhidraExporter
from drdeconstruct.software.analyzer import SoftwareAnalyzer
from drdeconstruct.software.symbols import (
    GlobalName,
    apply_symbol_map,
    build_symbol_map,
    hints_context,
)
from drdeconstruct.web.analyzer import WebAnalyzer
from drdeconstruct.web.extract import build_snapshot
from drdeconstruct.web.fetcher import SiteFetcher
from drdeconstruct.web.mirror import mirror_page
from drdeconstruct.web.scaffold import write_scaffold


def build_engine(settings: Settings) -> tuple[LLMBackend, Orchestrator]:
    llm = make_backend(settings)
    orch = Orchestrator(
        {
            Domain.SOFTWARE: SoftwareAnalyzer(llm),
            Domain.HARDWARE: HardwareAnalyzer(llm),
            Domain.WEB: WebAnalyzer(llm),
        }
    )
    return llm, orch


def build_orchestrator(settings: Settings) -> Orchestrator:
    return build_engine(settings)[1]


def analyze_functions(
    orch: Orchestrator,
    base: AnalysisRequest,
    functions: list[tuple[str, str]],
    llm: LLMBackend | None = None,
) -> dict[str, dict]:
    """Analizza più funzioni dello stesso programma in due passaggi.

    1. Con `llm` e almeno due funzioni, una mappa unica dei nomi per funzioni e
       globali opache (vedi `software.symbols`), così restano coerenti.
    2. Ogni funzione, con i nomi sicuri già sostituiti, viene analizzata da sola;
       un errore su una non ferma le altre.
    """
    symbols: dict[str, GlobalName] = {}
    if llm is not None and len(functions) > 1:
        print("[*] Passaggio 1: nomi comuni a tutto il programma", file=sys.stderr)
        try:
            symbols = build_symbol_map(llm, functions, base.arch, base.context)
        except BackendError as exc:
            print(f"    mappa dei nomi non disponibile, proseguo senza: {exc}", file=sys.stderr)

    results: dict[str, dict] = {}
    for i, (name, code) in enumerate(functions, 1):
        print(f"[{i}/{len(functions)}] {name}", file=sys.stderr)
        code, hints = apply_symbol_map(code, symbols)
        context = "\n\n".join(part for part in (base.context, hints_context(hints)) if part)
        req = replace(
            base, content=code, context=context, kind=base.kind or ArtifactKind.PSEUDOCODE_C
        )
        try:
            results[name] = orch.run(req).model_dump()
        except RefusalError as exc:
            print(f"    rifiutata: {exc}", file=sys.stderr)
            results[name] = {"error": str(exc), "refused": True}
        except BackendError as exc:
            print(f"    errore: {exc}", file=sys.stderr)
            results[name] = {"error": str(exc)}
    return {
        "symbol_map": {k: v.model_dump() for k, v in symbols.items()},
        "functions": results,
    }


def _add_engine_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--backend", choices=BACKENDS, help="Motore LLM (default da DRDEC_BACKEND)")
    p.add_argument("--model")
    p.add_argument("--context", default="", help="Cosa sai già del target")
    p.add_argument("-o", "--output", type=Path, help="Salva il risultato qui")
    p.add_argument(
        "--no-global-names",
        action="store_true",
        help="Salta il passaggio che dà nomi coerenti a funzioni e globali (più veloce)",
    )


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

    pt = sub.add_parser(
        "port",
        help="Traduce il TUO codice sorgente in un altro linguaggio (Rust in primis).",
        description=(
            "Traduce file o cartella di codice sorgente scritto da te, pezzo per pezzo, con i "
            "corpi delle funzioni implementati, e scrive una CHECKLIST.md dei punti da "
            "verificare. Se il compilatore è installato controlla il risultato e rimanda al "
            "modello i pezzi con errori. La traduzione automatica va sempre testata."
        ),
    )
    pt.add_argument("source", type=Path, help="File o cartella del tuo codice")
    pt.add_argument("--out", type=Path, required=True, metavar="CARTELLA", help="Dove scrivere")
    pt.add_argument(
        "--lang",
        choices=("rust", "python", "c"),
        default="rust",
        help="Linguaggio di destinazione (default: rust)",
    )
    pt.add_argument("--no-check", action="store_true", help="Non compilare il risultato")
    pt.add_argument(
        "--fix-rounds",
        type=int,
        default=1,
        help="Giri di correzione dopo gli errori del compilatore (default: 1, 0 = nessuno)",
    )
    _add_engine_args(pt)

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

    e = sub.add_parser(
        "eval",
        help="Misura la qualità della rinomina su casi con i nomi veri noti (usa il modello).",
    )
    e.add_argument(
        "cases", type=Path, nargs="?", help="Cartella dei casi (default: quelli inclusi)"
    )
    _add_engine_args(e)
    doc = sub.add_parser(
        "doctor", help="Controlla cosa è pronto: motore IA, Ghidra, flashrom, Rust."
    )
    doc.add_argument("--backend", choices=BACKENDS, help="Motore da controllare")
    _add_home_parser(sub)
    return p


def _add_home_parser(sub) -> None:
    h = sub.add_parser("home", help="Dispositivi smart home: Xiaomi, Aqara, Tapo (sola lettura).")
    hs = h.add_subparsers(dest="home_command", required=True)

    s = hs.add_parser("scan", help="Cerca i dispositivi via Bluetooth LE e rete locale.")
    s.add_argument("--timeout", type=float, default=4.0)
    s.add_argument("--no-ble", action="store_true", help="Salta il Bluetooth")
    s.add_argument("--no-lan", action="store_true", help="Salta la rete locale")
    s.add_argument("-o", "--output", type=Path, help="Salva l'inventario qui")

    g = hs.add_parser("guide", help="Spiega come collegarsi a ogni dispositivo trovato.")
    g.add_argument("--inventory", type=Path, help="Inventario salvato con `home scan -o`")
    g.add_argument("--timeout", type=float, default=4.0)
    _add_engine_args(g)

    m = hs.add_parser("miio", help="Interroga un dispositivo Xiaomi WiFi (serve il token).")
    m.add_argument("ip")
    m.add_argument("--token", help="Token a 32 caratteri (o DRDEC_MIIO_TOKEN, o richiesta)")
    m.add_argument("--method", default="miIO.info")
    m.add_argument("--params", default="[]", help="Parametri JSON")
    m.add_argument("--confirm", action="store_true", help="Consenti comandi che modificano")
    m.add_argument("-o", "--output", type=Path)

    t = hs.add_parser("tapo", help="Interroga un dispositivo Tapo (serve l'account TP-Link).")
    t.add_argument("ip")
    t.add_argument("--user", help="Email TP-Link (o DRDEC_TAPO_USER)")
    t.add_argument("--method", default="get_device_info")
    t.add_argument("--params", default="{}", help="Parametri JSON")
    t.add_argument("--confirm", action="store_true", help="Consenti comandi che modificano")
    t.add_argument("-o", "--output", type=Path)

    v = hs.add_parser("valetudo", help="Legge stato e modello di un robot con Valetudo.")
    v.add_argument("ip")
    v.add_argument("-o", "--output", type=Path)


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    if args.backend:
        settings = replace(settings, backend=args.backend)
    if args.model:
        settings = replace(settings, model=args.model)
    return settings


def _cmd_analyze(args: argparse.Namespace) -> str:
    content = args.file.read_text(encoding="utf-8", errors="replace")
    llm, orch = build_engine(_settings(args))
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
    results = analyze_functions(
        orch, base, [(c.name, c.code) for c in chunks], llm=None if args.no_global_names else llm
    )
    return json.dumps(results, indent=2, ensure_ascii=False)


def run_scaffold(
    settings: Settings,
    functions: list,
    out_dir: Path,
    language: str = "c",
    arch: str | None = None,
    context: str = "",
    source: str | None = None,
    progress=None,
    on_update=None,
    should_stop=None,
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
        progress=progress
        or (lambda i, n, name: print(f"[{i}/{n}] scheletro {name}", file=sys.stderr)),
        on_update=on_update,
        should_stop=should_stop,
    )
    if not module.functions:
        errors = "; ".join(f"{k}: {v}" for k, v in module.failed.items())
        raise DrDeconstructError(
            f"Nessuna funzione elaborata: {errors}" if errors else "Interrotto prima di iniziare."
        )
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


def _cmd_port(args: argparse.Namespace) -> str:
    from drdeconstruct.software.port import run_port
    from drdeconstruct.software.port_source import load_sources

    files = load_sources(args.source)
    units = sum(len(f.units) for f in files)
    print(f"[*] {len(files)} file, {units} pezzi da tradurre in {args.lang}", file=sys.stderr)
    project, paths = run_port(
        make_backend(_settings(args)),
        files,
        args.out,
        args.lang,
        args.context,
        name=args.source.resolve().stem or "porting",
        check=not args.no_check,
        fix_rounds=max(args.fix_rounds, 0),
        progress=lambda i, n, name: print(f"[{i}/{n}] {name}", file=sys.stderr),
        stage=lambda text: print(f"[*] {text}", file=sys.stderr),
    )
    for path in paths:
        print(f"[*] Scritto: {path}", file=sys.stderr)
    print(f"[*] Leggi {Path(args.out) / 'CHECKLIST.md'} prima di usare il codice.", file=sys.stderr)
    return project.model_dump_json(indent=2)


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

    llm, orch = build_engine(_settings(args))
    base = AnalysisRequest(
        content="",
        kind=ArtifactKind.PSEUDOCODE_C,
        arch=program.arch,
        context=args.context,
        source_name=args.binary.name,
    )
    results = analyze_functions(
        orch,
        base,
        [(f"{f.name}@{f.entry}", f.code) for f in program.functions],
        llm=None if args.no_global_names else llm,
    )
    return json.dumps(
        {"program": program.program, "language": program.language, **results},
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


def _cmd_eval(args: argparse.Namespace) -> str:
    from drdeconstruct.evaluation import load_cases, report, run_case

    cases = load_cases(args.cases) if args.cases else load_cases()
    if not cases:
        raise DrDeconstructError(f"Nessun caso .json in {args.cases}.")
    llm, orch = build_engine(_settings(args))
    names_llm = None if args.no_global_names else llm
    results = []
    for case in cases:
        print(f"[*] Caso {case.name}", file=sys.stderr)
        context = "\n\n".join(part for part in (case.context, args.context) if part)
        results.append(
            run_case(
                replace(case, context=context),
                lambda req, fns: analyze_functions(orch, req, fns, llm=names_llm),
            )
        )
    return report(results)


def _secret(value: str | None, env: str, prompt: str) -> str:
    """Prende un segreto da argomento, variabile d'ambiente o richiesta a terminale."""
    secret = value or os.environ.get(env) or getpass.getpass(prompt)
    if not secret:
        raise DrDeconstructError(f"Manca {prompt.rstrip(': ')}.")
    return secret


def _json_arg(text: str):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise DrDeconstructError(f"Parametri non validi (serve JSON): {text}") from exc


def _cmd_home(args: argparse.Namespace) -> str:
    from drdeconstruct.smarthome.inventory import build_inventory, default_scanners
    from drdeconstruct.smarthome.safety import CommandGuard

    cmd = args.home_command
    if cmd == "scan":
        scanners = default_scanners(args.timeout, ble=not args.no_ble, lan=not args.no_lan)
        inv = build_inventory(scanners)
        for channel, error in inv.errors.items():
            print(f"[!] {channel}: {error}", file=sys.stderr)
        print(f"[*] {len(inv.devices)} dispositivi trovati", file=sys.stderr)
        return inv.to_json()
    if cmd == "guide":
        from drdeconstruct.smarthome.guide import SmartHomeAdvisor

        if args.inventory:
            inventory = _json_arg(args.inventory.read_text(encoding="utf-8"))
        else:
            inventory = build_inventory(default_scanners(args.timeout)).to_dict()
        advisor = SmartHomeAdvisor(make_backend(_settings(args)))
        return advisor.advise(inventory, args.context).model_dump_json(indent=2)
    guard = CommandGuard(confirmed=getattr(args, "confirm", False))
    if cmd == "miio":
        from drdeconstruct.smarthome.miio import MiioClient

        token = _secret(args.token, "DRDEC_MIIO_TOKEN", "Token miIO: ")
        result = MiioClient(args.ip, token).send(args.method, _json_arg(args.params), guard)
    elif cmd == "tapo":
        from drdeconstruct.smarthome.tapo import TapoClient

        user = args.user or os.environ.get("DRDEC_TAPO_USER") or input("Email TP-Link: ")
        password = _secret(None, "DRDEC_TAPO_PASSWORD", "Password TP-Link: ")
        params = _json_arg(args.params) or None
        result = TapoClient(args.ip, user, password).request(args.method, params, guard)
    else:
        from drdeconstruct.smarthome.valetudo import read_robot

        result = read_robot(args.ip)
    return json.dumps(result, indent=2, ensure_ascii=False)


def _cmd_doctor(args) -> str:
    from drdeconstruct.doctor import format_checks, run_checks

    settings = Settings.from_env()
    if args.backend:
        settings = replace(settings, backend=args.backend)
    return format_checks(run_checks(settings))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    commands = {
        "analyze": _cmd_analyze,
        "scaffold": _cmd_scaffold,
        "port": _cmd_port,
        "decompile": _cmd_decompile,
        "web": _cmd_web,
        "eval": _cmd_eval,
        "home": _cmd_home,
        "doctor": _cmd_doctor,
    }
    try:
        output = commands[args.command](args)
    except (DrDeconstructError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "output", None):
        args.output.write_text(output, encoding="utf-8")
        print(f"[*] Salvato in {args.output}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
