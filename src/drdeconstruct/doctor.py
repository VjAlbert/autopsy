"""Controllo del sistema: cosa è pronto e cosa manca, in parole semplici.

Usato dalla schermata iniziale della GUI e da `drdec doctor`. Ogni controllo
dice se il componente è pronto, cosa significa e come sistemarlo. Nessun
controllo modifica il sistema; quello di Ollama fa solo una richiesta locale.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from drdeconstruct.config import Settings

Which = Callable[[str], str | None]
Opener = Callable[..., object]

CLAUDE_DOCS = "https://code.claude.com/docs/en/setup"
OLLAMA_DOWNLOAD = "https://ollama.com/download"
GHIDRA_DOWNLOAD = "https://github.com/NationalSecurityAgency/ghidra/releases"
JAVA_DOWNLOAD = "https://adoptium.net/temurin/releases/?version=21"
FLASHROM_DOCS = "https://www.flashrom.org/"
RUST_DOWNLOAD = "https://rustup.rs/"

# Installer ufficiali di Claude Code (una riga, senza Node.js).
CLAUDE_INSTALL_WINDOWS = "irm https://claude.ai/install.ps1 | iex"
CLAUDE_INSTALL_UNIX = "curl -fsSL https://claude.ai/install.sh | bash"


@dataclass(frozen=True)
class Check:
    key: str
    title: str
    ok: bool
    detail: str
    fix: str = ""
    link: str = ""
    optional: bool = False

    @property
    def symbol(self) -> str:
        if self.ok:
            return "✓"
        return "○" if self.optional else "✗"


def check_claude_code(which: Which = shutil.which, home: Path | None = None) -> Check:
    from drdeconstruct.llm.claude_code import find_claude

    path = find_claude(which, home)
    if path:
        return Check(
            "claude-code",
            "Claude Code",
            True,
            "Installato. Usa il tuo abbonamento claude.ai, nessuna chiave da inserire.",
            fix="Se è la prima volta, premi «Accedi a Claude» e completa il login nel browser.",
        )
    return Check(
        "claude-code",
        "Claude Code",
        False,
        "Non trovato. Serve per usare il motore «Claude» con il tuo abbonamento.",
        fix="Premi «Installa Claude Code», poi «Accedi a Claude» e riavvia DrDeconstruct.",
        link=CLAUDE_DOCS,
    )


def check_ollama(host: str, model: str, opener: Opener = urllib.request.urlopen) -> Check:
    url = host.rstrip("/") + "/api/tags"
    try:
        with opener(url, timeout=2) as resp:  # type: ignore[attr-defined]
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except (OSError, ValueError):
        return Check(
            "ollama",
            "Ollama (modello sul tuo PC)",
            False,
            f"Non risponde su {host}.",
            fix=f"Installa Ollama e avvialo; poi scarica il modello con «ollama pull {model}».",
            link=OLLAMA_DOWNLOAD,
        )
    names = {m.get("name", "") for m in data.get("models", [])}
    if model in names or f"{model}:latest" in names:
        return Check("ollama", "Ollama (modello sul tuo PC)", True, f"Attivo, modello {model}.")
    return Check(
        "ollama",
        "Ollama (modello sul tuo PC)",
        False,
        f"Attivo, ma il modello {model} non è ancora scaricato.",
        fix=f"Apri un terminale e scrivi: ollama pull {model}",
        link=OLLAMA_DOWNLOAD,
    )


def check_api(env: Mapping[str, str] = os.environ) -> Check:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        installed = False
    else:
        installed = True
    if installed and env.get("ANTHROPIC_API_KEY"):
        return Check("api", "API Anthropic", True, "Chiave presente (consumo a pagamento).")
    return Check(
        "api",
        "API Anthropic",
        False,
        "Spenta: è facoltativa e a consumo. Non serve se usi Claude Code o Ollama.",
        fix="Imposta la variabile ANTHROPIC_API_KEY solo se vuoi davvero pagare a consumo.",
        optional=True,
    )


def check_ghidra(env: Mapping[str, str] = os.environ, which: Which = shutil.which) -> Check:
    base = env.get("GHIDRA_INSTALL_DIR")
    name = "analyzeHeadless.bat" if sys.platform == "win32" else "analyzeHeadless"
    if not base or not (Path(base) / "support" / name).exists():
        detail = (
            "Cartella indicata non valida: non contiene support/" + name
            if base
            else "Non configurato. Serve solo per aprire programmi e firmware (.exe, .bin)."
        )
        return Check(
            "ghidra",
            "Ghidra (decompilatore gratuito)",
            False,
            detail,
            fix="Scarica Ghidra, estrai lo zip e premi «Indica la cartella di Ghidra».",
            link=GHIDRA_DOWNLOAD,
            optional=True,
        )
    java_home = env.get("JAVA_HOME")
    if not which("java") and not (java_home and Path(java_home).exists()):
        return Check(
            "ghidra",
            "Ghidra (decompilatore gratuito)",
            False,
            "Ghidra trovato, ma manca Java 21, che Ghidra usa per funzionare.",
            fix="Installa Java 21 (Temurin) e riavvia DrDeconstruct.",
            link=JAVA_DOWNLOAD,
            optional=True,
        )
    return Check("ghidra", "Ghidra (decompilatore gratuito)", True, f"Pronto in {base}.")


def check_flashrom(which: Which = shutil.which) -> Check:
    if which("flashrom"):
        return Check("flashrom", "flashrom (lettura memorie flash)", True, "Installato.")
    return Check(
        "flashrom",
        "flashrom (lettura memorie flash)",
        False,
        "Non installato. Serve solo per leggere o scrivere chip di memoria con un programmatore.",
        fix="Installalo solo se hai un programmatore (es. CH341A).",
        link=FLASHROM_DOCS,
        optional=True,
    )


def check_rust(which: Which = shutil.which) -> Check:
    if which("cargo"):
        return Check(
            "rust",
            "Rust (controllo del porting)",
            True,
            "Installato: il porting in Rust viene compilato e corretto da solo.",
        )
    return Check(
        "rust",
        "Rust (controllo del porting)",
        False,
        "Non installato. Serve solo per far compilare e correggere in automatico il codice "
        "tradotto in Rust; la traduzione funziona anche senza.",
        fix="Installalo da rustup.rs (gratuito), poi riavvia DrDeconstruct.",
        link=RUST_DOWNLOAD,
        optional=True,
    )


def engine_check(
    settings: Settings,
    env: Mapping[str, str] = os.environ,
    which: Which = shutil.which,
    opener: Opener = urllib.request.urlopen,
) -> Check:
    """Controlla solo il motore scelto."""
    if settings.backend == "ollama":
        model = settings.model or "qwen2.5-coder:14b"
        return check_ollama(settings.ollama_host, model, opener)
    if settings.backend == "api":
        return check_api(env)
    return check_claude_code(which, Path.home() if which is shutil.which else None)


def run_checks(
    settings: Settings,
    env: Mapping[str, str] = os.environ,
    which: Which = shutil.which,
    opener: Opener = urllib.request.urlopen,
) -> list[Check]:
    """Il motore scelto per primo, poi gli strumenti facoltativi."""
    return [
        engine_check(settings, env, which, opener),
        check_ghidra(env, which),
        check_flashrom(which),
        check_rust(which),
    ]


def login_command(platform: str = sys.platform, exe: str | None = None) -> list[str]:
    """Apre una finestra di terminale con `claude`, che guida il login nel browser."""
    if exe is None:
        from drdeconstruct.llm.claude_code import find_claude

        exe = find_claude(home=Path.home()) or "claude"
    if platform == "win32":
        return ["cmd.exe", "/c", "start", "Claude", "cmd.exe", "/k", exe]
    if platform == "darwin":
        return ["osascript", "-e", 'tell application "Terminal" to do script "claude"']
    return ["x-terminal-emulator", "-e", exe]


def install_command(platform: str = sys.platform) -> list[str]:
    """Apre un terminale che esegue l'installer ufficiale di Claude Code."""
    if platform == "win32":
        return [
            "cmd.exe",
            "/c",
            "start",
            "Installa Claude Code",
            "powershell.exe",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            CLAUDE_INSTALL_WINDOWS,
        ]
    if platform == "darwin":
        return [
            "osascript",
            "-e",
            f'tell application "Terminal" to do script "{CLAUDE_INSTALL_UNIX}"',
        ]
    return ["x-terminal-emulator", "-e", "bash", "-c", CLAUDE_INSTALL_UNIX + "; exec bash"]


def format_checks(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        lines.append(f"{c.symbol} {c.title}: {c.detail}")
        if not c.ok and c.fix:
            lines.append(f"    → {c.fix}")
        if not c.ok and c.link:
            lines.append(f"    {c.link}")
    return "\n".join(lines)


def bundle_self_check() -> list[tuple[str, bool, str]]:
    """Verifica che l'exe contenga tutto ciò che serve (usato dalla build Windows).

    Ogni voce è (nome, ok, dettaglio). Non tocca dispositivi: carica solo librerie e file.
    """
    import importlib

    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn: Callable[[], object]) -> None:
        try:
            detail = fn()
            results.append((name, True, str(detail or "")))
        except Exception as exc:  # il rapporto deve elencare tutto, anche gli errori
            results.append((name, False, f"{type(exc).__name__}: {exc}"))

    def libusb():
        from drdeconstruct.acquisition.usb import _load_usb_backend

        backend = _load_usb_backend()
        if backend is None:
            raise RuntimeError("nessun backend libusb")
        return type(backend).__module__

    def serial_ports():
        from serial.tools import list_ports

        return f"{len(list_ports.comports())} porte"

    def bleak_backend():
        import bleak

        if sys.platform == "win32":
            importlib.import_module("bleak.backends.winrt.scanner")
        return bleak.__name__

    def data_files():
        from drdeconstruct.evaluation import CASES_DIR
        from drdeconstruct.preprocess.ghidra import SCRIPTS_DIR

        cases = list(CASES_DIR.glob("*.json"))
        scripts = list(SCRIPTS_DIR.iterdir())
        if not cases or not scripts:
            raise RuntimeError(f"casi={len(cases)} script Ghidra={len(scripts)}")
        return f"casi={len(cases)} script Ghidra={len(scripts)}"

    check("Qt", lambda: importlib.import_module("PySide6.QtWidgets").__name__)
    check("libusb", libusb)
    check("seriale", serial_ports)
    check("bluetooth", bleak_backend)
    for module in ("zeroconf", "cryptography.hazmat.primitives.ciphers", "anthropic"):
        check(module, lambda m=module: importlib.import_module(m).__name__)
    check("file di dati", data_files)
    return results
