"""Porting del codice sorgente dell'utente in un altro linguaggio (Rust in primis).

Flusso:
1. `port_source` legge file o cartella e divide ogni file in pezzi
   (definizioni + funzioni, oppure il file intero).
2. Prima di chiamare il modello si decidono i nomi di destinazione di tutte le
   funzioni (snake_case/CamelCase), così i pezzi tradotti separatamente si
   chiamano tra loro con gli stessi nomi.
3. Il modello traduce un pezzo alla volta, con i corpi implementati, e
   restituisce per ognuno una checklist dei punti incerti.
4. Il risultato si scrive come progetto pronto da compilare (per Rust un
   progetto Cargo) con `CHECKLIST.md`.
5. Se il compilatore è installato, il progetto viene controllato e i pezzi con
   errori vengono rimandati al modello con gli errori (giri di correzione).

Limite onesto: una traduzione automatica di un programma non banale non è mai
garantita corretta. Il porting accelera il lavoro; i test che confrontano
originale e versione tradotta restano indispensabili.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from drdeconstruct.config import NO_WINDOW
from drdeconstruct.core.errors import BackendError, DrDeconstructError
from drdeconstruct.llm.base import LLMBackend
from drdeconstruct.software.port_prompts import (
    FIX_SYSTEM,
    SYSTEM,
    build_fix_message,
    build_user_message,
)
from drdeconstruct.software.port_schemas import (
    CheckItem,
    CompileIssue,
    PortedUnit,
    PortFile,
    PortProject,
    SourceUnitInfo,
)
from drdeconstruct.software.port_source import (
    CONTEXT_CHARS,
    LARGE_UNIT_CHARS,
    SOURCE_LANGUAGE_LABELS,
    SourceFile,
)
from drdeconstruct.software.scaffold import Language, identifier, unique

DEFAULT_TARGET = Language.RUST
TARGETS = tuple(lang.value for lang in Language)
# Quanti nomi passare al modello per ogni pezzo (quelli citati nel pezzo per primi).
MAX_NAMES = 150

Runner = Callable[[list[str], Path], tuple[int, str]]
Which = Callable[[str], str | None]


# --- Nomi -----------------------------------------------------------------


def snake_case(name: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return re.sub(r"_+", "_", s).lower()


def camel_case(name: str) -> str:
    parts = re.split(r"[_\W]+", name, flags=re.ASCII)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def target_name(original: str, target: Language) -> str:
    """Il nome idiomatico nel linguaggio di destinazione."""
    if target is Language.C:
        return identifier(original, target)
    if original[:1].isupper() and not original.isupper():
        return identifier(camel_case(original), target)  # tipo/classe
    return identifier(snake_case(original), target)


def plan_names(files: list[SourceFile], target: Language) -> tuple[dict[str, str], list[str]]:
    """Nome originale -> nome di destinazione per tutte le funzioni del progetto."""
    names: dict[str, str] = {}
    used: set[str] = set()
    notes: list[str] = []
    for f in files:
        own = dict.fromkeys([u.name for u in f.units if u.kind == "function"] + f.symbols)
        for original in own:
            if original in names:
                notes.append(
                    f"Il nome {original} compare in più file: controlla quale versione "
                    "viene chiamata nella traduzione."
                )
                continue
            names[original] = unique(target_name(original, target), used)
    return names, notes


def module_names(files: list[SourceFile], target: Language) -> list[str]:
    used: set[str] = {"lib", "main", "mod", "crate", "self", "super", "std", "core"}
    out = []
    for f in files:
        stem = Path(f.path).stem
        out.append(unique(identifier(snake_case(stem), target, "module"), used))
    return out


def names_for(code: str, own: list[str], names: dict[str, str]) -> dict[str, str]:
    """I nomi utili per un pezzo: quelli citati nel codice e quelli del suo file."""
    cited = [n for n in names if re.search(rf"\b{re.escape(n)}\b", code)]
    picked = dict.fromkeys(cited + [n for n in own if n in names])
    return {n: names[n] for n in list(picked)[:MAX_NAMES]}


# --- Traduzione -----------------------------------------------------------


_PLACEHOLDER = re.compile(r"todo!\(|unimplemented!\(|NotImplementedError|\bTODO\b")


_DEFINES = {
    Language.RUST: re.compile(r"\bfn\s+(\w+)"),
    Language.PYTHON: re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.M),
    Language.C: re.compile(r"\b(\w+)\s*\([^;{]*\)\s*\{"),
}


def _force_name(
    unit: PortedUnit,
    original: str,
    expected: str | None,
    target: Language = DEFAULT_TARGET,
    reserved: frozenset[str] = frozenset(),
) -> PortedUnit:
    """Usa il nome deciso in anticipo anche se il modello ne ha scelto un altro."""
    update: dict = {"original_name": original}
    code = unit.code
    if expected:
        defined = _DEFINES[Language(target)].search(code)
        wrong = {unit.name} | ({defined.group(1)} if defined else set())
        for name in wrong - {expected} - reserved:
            if name:
                code = re.sub(rf"\b{re.escape(name)}\b", expected, code)
        update["name"] = expected
        update["code"] = code
    checklist = list(unit.checklist)
    if _PLACEHOLDER.search(code):
        checklist.insert(
            0,
            CheckItem(
                kind="behavior",
                severity="high",
                text="La traduzione contiene ancora un segnaposto (TODO/todo!): completala a mano.",
            ),
        )
    update["checklist"] = checklist
    return unit.model_copy(update=update)


class PortGenerator:
    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def port_unit(
        self,
        src: SourceFile,
        unit,
        target: Language,
        names: dict[str, str],
        definitions: str = "",
        definitions_translated: bool = True,
        context: str = "",
    ) -> PortedUnit:
        own = [u.name for u in src.units if u.kind == "function"] + src.symbols
        user = build_user_message(
            unit.code,
            SOURCE_LANGUAGE_LABELS.get(src.language, src.language),
            target.value,
            unit.name,
            unit.kind,
            src.path,
            names_for(unit.code, own, names),
            definitions[:CONTEXT_CHARS],
            context,
            definitions_translated,
        )
        result = self.llm.structured(SYSTEM, user, PortedUnit)
        expected = names.get(unit.name) if unit.kind == "function" else None
        reserved = frozenset(names.values())
        result = _force_name(result, unit.name, expected, target, reserved)
        if len(unit.code) > LARGE_UNIT_CHARS:
            result.checklist.insert(
                0,
                CheckItem(
                    kind="other",
                    severity="high",
                    text=(
                        f"Pezzo molto lungo ({len(unit.code)} caratteri): controlla che la "
                        "traduzione sia completa; meglio dividerlo in funzioni più piccole."
                    ),
                ),
            )
        return result

    def generate(
        self,
        files: list[SourceFile],
        target: Language = DEFAULT_TARGET,
        context: str = "",
        name: str = "porting",
        progress: Callable[[int, int, str], None] | None = None,
        on_update: Callable[[PortProject], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> PortProject:
        """Traduce tutti i pezzi; un errore su un pezzo non ferma gli altri."""
        target = Language(target)
        names, notes = plan_names(files, target)
        modules = module_names(files, target)
        project = PortProject(
            name=identifier(snake_case(name), Language.RUST, "porting"),
            language=target.value,
            notes=notes,
        )
        total = sum(len(f.units) for f in files)
        done = 0
        stopped = False
        for src, module in zip(files, modules, strict=True):
            pf = PortFile(source=src.path, module=module, source_language=src.language)
            project.files.append(pf)
            translated_defs: str | None = None
            for unit in src.units:
                if should_stop and should_stop():
                    stopped = True
                    break
                done += 1
                label = f"{src.path}: {unit.name}"
                if progress:
                    progress(done, total, label)
                if unit.kind == "function" and translated_defs is not None:
                    defs, translated = translated_defs, True
                else:
                    defs, translated = src.definitions, False
                try:
                    ported = self.port_unit(src, unit, target, names, defs, translated, context)
                except BackendError as exc:
                    pf.failed[unit.name] = str(exc)
                else:
                    pf.units.append(ported)
                    pf.origins.append(
                        SourceUnitInfo(
                            file=src.path, name=unit.name, kind=unit.kind, lines=unit.lines
                        )
                    )
                    if unit.kind == "definitions":
                        translated_defs = ported.code
                if on_update:
                    on_update(project.model_copy(deep=True))
            if stopped:
                break
        if stopped:
            project.notes.append(f"Interrotto dall'utente: elaborati {done} pezzi su {total}.")
        return project

    def fix(
        self,
        project: PortProject,
        files: list[SourceFile],
        issues: list[CompileIssue],
        spans: dict[str, list[tuple[int, int, int, int]]],
    ) -> list[str]:
        """Rimanda al modello i pezzi con errori di compilazione. Ritorna i pezzi corretti."""
        target = Language(project.language)
        names, _ = plan_names(files, target)
        by_unit: dict[tuple[int, int], list[str]] = {}
        for issue in issues:
            where = locate(spans, issue.file, issue.line)
            if where is not None:
                by_unit.setdefault(where, []).append(f"riga {issue.line}: {issue.message}")
        fixed = []
        sources = {f.path: f for f in files}
        for (fi, ui), errors in by_unit.items():
            pf = project.files[fi]
            unit = pf.units[ui]
            origin = pf.origins[ui]
            src = sources.get(pf.source)
            original = next(
                (u.code for u in (src.units if src else []) if u.name == origin.name), ""
            )
            user = build_fix_message(
                original,
                unit.code,
                unit.imports,
                errors[:20],
                target.value,
                names_for(original, [], names),
            )
            try:
                new = self.llm.structured(FIX_SYSTEM, user, PortedUnit)
            except BackendError:
                continue
            expected = unit.name if origin.kind == "function" else None
            new = _force_name(new, unit.original_name, expected, target, frozenset(names.values()))
            # La checklist della prima traduzione resta valida: si somma a quella nuova.
            seen = {c.text for c in new.checklist}
            kept = [c for c in unit.checklist if c.text not in seen]
            pf.units[ui] = new.model_copy(update={"checklist": kept + new.checklist})
            fixed.append(f"{pf.source}: {origin.name}")
        return fixed


# --- Rendering ------------------------------------------------------------

_BANNER = [
    "Tradotto da DrDeconstruct a partire dal tuo codice sorgente.",
    "Traduzione automatica: compila e testa prima di fidarti. Vedi CHECKLIST.md.",
]


def _comment(target: Language) -> str:
    return "#" if target is Language.PYTHON else "//"


def _unit_header(target: Language, pf: PortFile, i: int) -> str:
    o = pf.origins[i]
    u = pf.units[i]
    lines = f", righe {o.lines[0]}-{o.lines[1]}" if o.lines else ""
    return f"{_comment(target)} --- {o.name} ({pf.source}{lines}) · confidenza: {u.confidence} ---"


def _dedupe(items) -> list[str]:
    return list(dict.fromkeys(i.strip() for i in items if i and i.strip()))


def _module_text(
    target: Language, pf: PortFile, prelude: list[str], start_line: int = 1
) -> tuple[str, list[tuple[int, int, int]]]:
    """Il testo di un modulo e, per ogni pezzo, le righe che occupa (inizio, fine, indice)."""
    c = _comment(target)
    lang = SOURCE_LANGUAGE_LABELS.get(pf.source_language, pf.source_language)
    out = [f"{c} {line}" for line in _BANNER]
    out.append(f"{c} Originale: {pf.source} ({lang})")
    out.append("")
    out += prelude
    imports = _dedupe(i for u in pf.units for i in u.imports)
    if imports:
        out += imports + [""]
    spans = []
    for i, unit in enumerate(pf.units):
        out.append(_unit_header(target, pf, i))
        first = len(out) + start_line
        out += unit.code.rstrip().splitlines()
        spans.append((first, len(out) + start_line - 1, i))
        out.append("")
    return "\n".join(out).rstrip() + "\n", spans


def _cargo_toml(project: PortProject) -> str:
    deps = _dedupe(d for f in project.files for u in f.units for d in u.dependencies)
    valid = [d for d in deps if re.match(r"^[\w-]+\s*=", d)]
    odd = [d for d in deps if d not in valid]
    lines = [
        "[package]",
        f'name = "{project.name}"',
        'version = "0.1.0"',
        'edition = "2021"',
        "",
        "[dependencies]",
    ]
    lines += valid
    lines += [f"# da controllare: {d}" for d in odd]
    return "\n".join(lines) + "\n"


def render_project(
    project: PortProject,
) -> tuple[dict[str, str], dict[str, list[tuple[int, int, int, int]]]]:
    """I file da scrivere e, per ogni file, dove cade ogni pezzo (per gli errori)."""
    target = Language(project.language)
    files: dict[str, str] = {}
    spans: dict[str, list[tuple[int, int, int, int]]] = {}
    multi = len(project.files) > 1
    if target is Language.RUST:
        files["Cargo.toml"] = _cargo_toml(project)
        lib = [f"//! {line}" for line in _BANNER]
        lib += ["", "#![allow(dead_code, unused_imports, unused_variables)]", ""]
        for pf in project.files:
            lib.append(f"pub mod {pf.module};")
            lib.append(f"pub use {pf.module}::*;")
        files["src/lib.rs"] = "\n".join(lib) + "\n"
        prelude = ["use crate::*;", ""] if multi else []
        for fi, pf in enumerate(project.files):
            text, s = _module_text(target, pf, prelude)
            path = f"src/{pf.module}.rs"
            files[path] = text
            spans[path] = [(a, b, fi, ui) for a, b, ui in s]
    else:
        ext = ".py" if target is Language.PYTHON else ".c"
        for fi, pf in enumerate(project.files):
            text, s = _module_text(target, pf, [])
            path = f"{pf.module}{ext}"
            files[path] = text
            spans[path] = [(a, b, fi, ui) for a, b, ui in s]
        if target is Language.PYTHON:
            deps = _dedupe(d for f in project.files for u in f.units for d in u.dependencies)
            if deps:
                files["requirements.txt"] = "\n".join(deps) + "\n"
    files["CHECKLIST.md"] = render_checklist(project)
    return files, spans


def locate(
    spans: dict[str, list[tuple[int, int, int, int]]], file: str, line: int
) -> tuple[int, int] | None:
    for a, b, fi, ui in spans.get(file.replace("\\", "/"), []):
        if a - 1 <= line <= b:  # la riga di intestazione conta come il pezzo
            return fi, ui
    return None


def preview(project: PortProject) -> str:
    """I sorgenti generati in un unico testo, per l'anteprima nella GUI."""
    files, _ = render_project(project)
    files.pop("CHECKLIST.md", None)
    return "\n".join(f"// ===== {name} =====\n{text}" for name, text in files.items())


_SEVERITY = {"high": "ALTA", "medium": "MEDIA", "low": "BASSA"}
_ORDER = {"high": 0, "medium": 1, "low": 2}

_HOW_TO = {
    Language.RUST: [
        "Installa Rust da https://rustup.rs se non l'hai già (gratuito).",
        "Nella cartella del progetto esegui `cargo build`: deve compilare senza errori.",
        "Esegui `cargo clippy` e leggi gli avvisi: spesso indicano traduzioni poco idiomatiche.",
        "Scrivi test in `tests/` che diano gli stessi input a originale e versione Rust "
        "e confrontino i risultati (vedi le voci [TEST] qui sotto).",
        "Controlla una per una le voci ALTA: sono quelle che possono cambiare il comportamento.",
    ],
    Language.PYTHON: [
        "Esegui `python -m py_compile` sui file generati.",
        "Installa le dipendenze di `requirements.txt`, se presente.",
        "Scrivi test che confrontino originale e versione Python sugli stessi input.",
        "Controlla una per una le voci ALTA.",
    ],
    Language.C: [
        "Compila con `gcc -Wall -Wextra -c` ogni file e correggi gli avvisi.",
        "Controlla allocazioni e liberazioni della memoria.",
        "Scrivi test che confrontino originale e versione C sugli stessi input.",
        "Controlla una per una le voci ALTA.",
    ],
}


def render_checklist(project: PortProject) -> str:
    target = Language(project.language)
    out = [
        f"# Checklist del porting: {project.name}",
        "",
        "La traduzione è automatica: accelera il lavoro ma non garantisce che il programma "
        "si comporti come l'originale. Usa questa lista per verificarla pezzo per pezzo.",
        "",
        "## Compilazione",
        "",
    ]
    if project.compiler is None:
        out.append("- Non controllata (compilatore non trovato o controllo disattivato).")
    elif project.compile_ok:
        out.append(f"- ✓ `{project.compiler}` senza errori.")
    else:
        out.append(f"- ✗ `{project.compiler}` segnala ancora errori:")
        for issue in project.compile_issues[:50]:
            where = f" (in {issue.unit})" if issue.unit else ""
            out.append(f"  - [ ] `{issue.file}:{issue.line}`{where}: {issue.message}")
    if project.fixed_units:
        out.append(f"- Corretti dopo gli errori del compilatore: {', '.join(project.fixed_units)}")
    out += ["", "## Come verificarla", ""]
    out += [f"{i}. {step}" for i, step in enumerate(_HOW_TO[target], 1)]

    counts = {"high": 0, "medium": 0, "low": 0}
    sections = []
    for pf in project.files:
        sections += ["", f"## {pf.source} → {pf.module}", ""]
        for i, unit in enumerate(pf.units):
            origin = pf.origins[i]
            sections.append(f"### {origin.name} → `{unit.name}` (confidenza: {unit.confidence})")
            if unit.notes.strip():
                sections.append("")
                sections.append(" ".join(unit.notes.split()))
            sections.append("")
            items = sorted(unit.checklist, key=lambda c: _ORDER[c.severity])
            for item in items:
                counts[item.severity] += 1
                kind = "TEST" if item.kind == "test" else item.kind
                sections.append(
                    f"- [ ] **{_SEVERITY[item.severity]}** [{kind}] {' '.join(item.text.split())}"
                )
            if unit.confidence == "low":
                counts["high"] += 1
                sections.append(
                    "- [ ] **ALTA** [behavior] Confidenza bassa: rileggi tutta la funzione "
                    "a confronto con l'originale."
                )
            if not items and unit.confidence != "low":
                sections.append("- [ ] **BASSA** [other] Rileggi e prova con un test.")
            sections.append("")
        for name, err in pf.failed.items():
            counts["high"] += 1
            sections.append(f"- [ ] **ALTA** `{name}` non tradotto: {' '.join(err.split())}")
    out += [
        "",
        "## Riepilogo",
        "",
        f"- Voci ALTA: {counts['high']} · MEDIA: {counts['medium']} · BASSA: {counts['low']}",
    ]
    out += [f"- {' '.join(n.split())}" for n in project.notes]
    return "\n".join(out + sections).rstrip() + "\n"


def write_files(files: dict[str, str], out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    written = []
    for name, text in files.items():
        path = out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


# --- Controllo con il compilatore ----------------------------------------

_ISSUE = re.compile(
    r"^(?P<file>[^\s:][^:\n]*):(?P<line>\d+):(?P<col>\d+): (?:fatal )?error(?:\[\w+\])?: "
    r"(?P<msg>.+)$",
    re.M,
)


def parse_issues(output: str) -> list[CompileIssue]:
    return [
        CompileIssue(
            file=m.group("file").replace("\\", "/"),
            line=int(m.group("line")),
            message=m.group("msg").strip(),
        )
        for m in _ISSUE.finditer(output)
    ]


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=600,
            errors="replace",
            **NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return 124, "tempo scaduto"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def checker_available(target: Language, which: Which = shutil.which) -> str | None:
    """Il comando di controllo disponibile per il linguaggio, o None."""
    target = Language(target)
    if target is Language.RUST:
        return "cargo check" if which("cargo") else None
    if target is Language.PYTHON:
        return "compile()"
    for cc in ("cc", "gcc", "clang"):
        if which(cc):
            return f"{cc} -fsyntax-only"
    return None


def check_project(
    out_dir: Path,
    files: dict[str, str],
    target: Language,
    which: Which = shutil.which,
    runner: Runner = _run,
) -> tuple[str | None, bool | None, list[CompileIssue], str]:
    """Compila senza eseguire. Ritorna (comando, ok, errori, output grezzo)."""
    target = Language(target)
    tool = checker_available(target, which)
    if tool is None:
        return None, None, [], ""
    if target is Language.PYTHON:
        issues = []
        for name, text in files.items():
            if name.endswith(".py"):
                try:
                    compile(text, name, "exec")
                except SyntaxError as exc:
                    issues.append(CompileIssue(file=name, line=exc.lineno or 1, message=exc.msg))
        return tool, not issues, issues, ""
    if target is Language.RUST:
        code, output = runner(["cargo", "check", "--quiet", "--message-format", "short"], out_dir)
    else:
        cc = tool.split()[0]
        sources = [name for name in files if name.endswith(".c")]
        code, output = runner([cc, "-fsyntax-only", *sources], out_dir)
    issues = parse_issues(output)
    if code != 0 and not issues:
        # Il controllo non è partito (es. dipendenze non scaricabili): non è colpa del codice.
        detail = " ".join(output.split())[:300] or f"codice di uscita {code}"
        raise DrDeconstructError(f"Il controllo con {tool} non è riuscito: {detail}")
    return tool, code == 0, issues, output


def run_port(
    llm: LLMBackend,
    files: list[SourceFile],
    out_dir: Path,
    target: str | Language = DEFAULT_TARGET,
    context: str = "",
    name: str = "porting",
    check: bool = True,
    fix_rounds: int = 1,
    progress: Callable[[int, int, str], None] | None = None,
    on_update: Callable[[PortProject], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    stage: Callable[[str], None] | None = None,
    which: Which = shutil.which,
    runner: Runner = _run,
) -> tuple[PortProject, list[Path]]:
    """Traduce, scrive, controlla con il compilatore e corregge. Usato da CLI e GUI."""
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise DrDeconstructError(f"{out_dir} non è vuota: scegli una cartella vuota o nuova.")
    target = Language(target)
    gen = PortGenerator(llm)
    project = gen.generate(files, target, context, name, progress, on_update, should_stop)
    if not any(pf.units for pf in project.files):
        errors = "; ".join(f"{k}: {v}" for pf in project.files for k, v in pf.failed.items())
        raise DrDeconstructError(
            f"Nessun pezzo tradotto: {errors}" if errors else "Interrotto prima di iniziare."
        )
    rendered, spans = render_project(project)
    paths = write_files(rendered, out_dir)
    if not check or (should_stop and should_stop()):
        return project, paths

    for round_no in range(fix_rounds + 1):
        tool = checker_available(target, which)
        if stage:
            stage(
                f"Controllo con {tool}…" if tool else "Compilatore non trovato: salto il controllo."
            )
        try:
            tool, ok, issues, _ = check_project(out_dir, rendered, target, which, runner)
        except DrDeconstructError as exc:
            project.notes.append(str(exc))
            break
        project.compiler, project.compile_ok = tool, ok
        for issue in issues:
            where = locate(spans, issue.file, issue.line)
            if where is not None:
                fi, ui = where
                issue.unit = project.files[fi].origins[ui].name
        project.compile_issues = issues
        if tool is None or ok or round_no == fix_rounds or (should_stop and should_stop()):
            break
        if stage:
            stage(f"Correggo {len(issues)} errori del compilatore (giro {round_no + 1})…")
        fixed = gen.fix(project, files, issues, spans)
        if not fixed:
            break
        project.fixed_units = _dedupe(project.fixed_units + fixed)
        rendered, spans = render_project(project)
        paths = write_files(rendered, out_dir)
        if on_update:
            on_update(project.model_copy(deep=True))

    rendered, _ = render_project(project)
    write_files({"CHECKLIST.md": rendered["CHECKLIST.md"]}, out_dir)
    return project, paths
