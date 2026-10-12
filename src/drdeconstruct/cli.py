"""Riga di comando: `drdec analyze` per i testi, `drdec decompile` per i binari,
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    commands = {"analyze": _cmd_analyze, "decompile": _cmd_decompile, "home": _cmd_home}
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
