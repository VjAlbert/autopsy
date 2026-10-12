"""Scheletri di codice riscritto, ricavati da funzioni decompilate.

Il modello produce per ogni funzione un piano strutturato (`FunctionSkeleton`):
firma ricostruita, tipi, costanti e passi del flusso descritti a parole. Da
quel piano questo modulo genera, senza altre chiamate al modello, un sorgente
leggibile in C (default), Python o Rust con nomi coerenti tra le funzioni,
commenti e TODO nei punti da completare.

Uso lecito: lo scheletro serve a capire e reinterpretare software proprio o
open source, per interoperabilità, didattica o ricerca di sicurezza. I corpi
delle funzioni restano da scrivere: è un punto di partenza, non una copia
dell'originale, e non serve a ricostruire software proprietario aggirandone
la licenza.
"""

from __future__ import annotations

import ast
import keyword
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from drdeconstruct.core.errors import BackendError
from drdeconstruct.llm.base import LLMBackend
from drdeconstruct.software.scaffold_prompts import SYSTEM, build_user_message
from drdeconstruct.software.scaffold_schemas import (
    Constant,
    FunctionSkeleton,
    ScaffoldModule,
    StructDef,
)


class Language(str, Enum):
    C = "c"
    PYTHON = "python"
    RUST = "rust"


LANGUAGES = tuple(lang.value for lang in Language)
DEFAULT_LANGUAGE = Language.C


@dataclass(frozen=True)
class SourceFunction:
    """Una funzione da trasformare in scheletro."""

    name: str
    code: str
    entry: str | None = None


# --- Generazione del piano ------------------------------------------------


class ScaffoldGenerator:
    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def skeleton(
        self,
        func: SourceFunction,
        language: Language = DEFAULT_LANGUAGE,
        arch: str | None = None,
        context: str = "",
        known_names: dict[str, str] | None = None,
    ) -> FunctionSkeleton:
        user = build_user_message(
            func.code, Language(language).value, func.name, arch, context, known_names
        )
        return self.llm.structured(SYSTEM, user, FunctionSkeleton)

    def generate(
        self,
        functions: list[SourceFunction],
        language: Language = DEFAULT_LANGUAGE,
        arch: str | None = None,
        context: str = "",
        source: str | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> ScaffoldModule:
        """Un piano per funzione; un errore su una funzione non ferma le altre.

        I nomi proposti vengono resi identificatori validi e unici, e ogni
        riferimento ai nomi originali viene sostituito con quello nuovo.
        """
        language = Language(language)
        skeletons: list[FunctionSkeleton] = []
        failed: dict[str, str] = {}
        renames: dict[str, str] = {}
        used: set[str] = set()
        for i, func in enumerate(functions, 1):
            if progress:
                progress(i, len(functions), func.name)
            try:
                sk = self.skeleton(func, language, arch, context, renames)
            except BackendError as exc:
                failed[func.name] = str(exc)
                continue
            name = unique(identifier(sk.name, language), used)
            renames[func.name] = name
            fixed = {"original_name": func.name, "entry": func.entry, "name": name}
            skeletons.append(sk.model_copy(update=fixed))

        skeletons = [apply_renames(sk, renames) for sk in skeletons]
        return ScaffoldModule(
            name=module_name(source),
            language=language.value,
            source=source,
            arch=arch,
            functions=skeletons,
            failed=failed,
            notes=_merge_notes(skeletons),
        )


def apply_renames(sk: FunctionSkeleton, renames: dict[str, str]) -> FunctionSkeleton:
    """Sostituisce i nomi originali (es. FUN_00401a20) con quelli semantici."""
    if not renames:
        return sk
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, renames)) + r")\b")

    def sub(text: str | None) -> str | None:
        return pattern.sub(lambda m: renames[m.group(1)], text) if text else text

    return sk.model_copy(
        update={
            "summary": sub(sk.summary),
            "steps": [
                s.model_copy(update={"description": sub(s.description), "todo": sub(s.todo)})
                for s in sk.steps
            ],
            "calls": [sub(c) for c in sk.calls],
        }
    )


def _merge_notes(skeletons: list[FunctionSkeleton]) -> list[str]:
    """Segnala strutture o costanti con lo stesso nome ma definizioni diverse."""
    notes = []
    for label, items in (
        ("Struttura", lambda sk: sk.structs),
        ("Costante", lambda sk: sk.constants),
    ):
        seen: dict[str, tuple[str, object]] = {}
        for sk in skeletons:
            for item in items(sk):
                prev = seen.get(item.name)
                if prev is None:
                    seen[item.name] = (sk.name, item)
                elif prev[1] != item:
                    notes.append(
                        f"{label} {item.name}: definizioni diverse in {prev[0]} e {sk.name}; "
                        f"tenuta quella di {prev[0]}."
                    )
    return notes


# --- Identificatori e tipi ------------------------------------------------

_C_KEYWORDS = frozenset(
    "auto break case char const continue default do double else enum extern float for goto "
    "if inline int long register restrict return short signed sizeof static struct switch "
    "typedef union unsigned void volatile while bool true false".split()
)
_RUST_KEYWORDS = frozenset(
    "as break const continue crate else enum extern false fn for if impl in let loop match mod "
    "move mut pub ref return self Self static struct super trait true type unsafe use where "
    "while async await dyn abstract become box do final macro override priv typeof unsized "
    "virtual yield try".split()
)
_KEYWORDS = {
    Language.C: _C_KEYWORDS,
    Language.PYTHON: frozenset(keyword.kwlist) | {"Any"},
    Language.RUST: _RUST_KEYWORDS,
}


def identifier(text: str, language: Language = DEFAULT_LANGUAGE, fallback: str = "func") -> str:
    """Rende `text` un identificatore valido e non riservato nel linguaggio."""
    s = re.sub(r"\W+", "_", text.strip(), flags=re.ASCII).strip("_") or fallback
    if s[0].isdigit():
        s = f"_{s}"
    if s in _KEYWORDS[Language(language)]:
        s += "_"
    return s


def unique(name: str, used: set[str]) -> str:
    candidate, n = name, 2
    while candidate in used:
        candidate, n = f"{name}_{n}", n + 1
    used.add(candidate)
    return candidate


def module_name(source: str | None) -> str:
    stem = Path(source).stem if source else ""
    return identifier(stem.lower(), Language.PYTHON, fallback="scaffold")


_C_TYPE = re.compile(r"^[A-Za-z_][\w ]*[\s\*]*$", re.ASCII)
_RUST_TYPE = re.compile(r"^[\w&'\[\]<>(),:; \*]+$", re.ASCII)
_FALLBACK_TYPE = {Language.C: "intptr_t", Language.PYTHON: "Any", Language.RUST: "usize"}


def clean_type(text: str, language: Language) -> str:
    """Accetta il tipo proposto solo se è sintatticamente plausibile."""
    t = " ".join(text.split())
    if language is Language.PYTHON:
        try:
            ast.parse(t, mode="eval")
            ok = bool(t)
        except SyntaxError:
            ok = False
    elif language is Language.C:
        ok = bool(_C_TYPE.match(t))
    else:
        ok = bool(_RUST_TYPE.match(t)) and t.count("<") == t.count(">")
    return t if ok and len(t) <= 80 else _FALLBACK_TYPE[language]


_NUMBER = re.compile(r"^(-?)(0[xX][0-9A-Fa-f]+|0[bB][01]+|\d+\.\d+|\d+)([uUlL]*)$", re.ASCII)


def clean_number(value: str | None) -> str | None:
    """Il letterale numerico senza suffissi C, o None se non è un numero."""
    m = _NUMBER.match((value or "").strip())
    if not m:
        return None
    digits = m.group(2)
    if digits.isdigit():
        digits = str(int(digits))  # niente zeri iniziali: in C sarebbero ottali
    return f"{m.group(1)}{digits}"


def _line(text: str | None) -> str:
    return " ".join((text or "").split())


# --- Rendering ------------------------------------------------------------


def _banner(module: ScaffoldModule) -> list[str]:
    origin = module.source or "codice decompilato"
    arch = f" ({module.arch})" if module.arch else ""
    return [
        f"Scheletro generato da DrDeconstruct a partire da {origin}{arch}.",
        "Punto di partenza da completare: firme, tipi e flusso sono dedotti dal",
        "decompilato e possono essere sbagliati; i corpi delle funzioni vanno scritti.",
        "Usalo su software tuo o open source, per interoperabilità, didattica o",
        "sicurezza, rispettando la licenza dell'originale.",
    ]


def _unique_defs(module: ScaffoldModule, language: Language):
    """Strutture e costanti di tutte le funzioni, senza duplicati, con nomi validi."""
    structs: dict[str, StructDef] = {}
    consts: dict[str, Constant] = {}
    for sk in module.functions:
        for s in sk.structs:
            structs.setdefault(identifier(s.name, language, "Struct"), s)
        for c in sk.constants:
            consts.setdefault(identifier(c.name, language, "CONST"), c)
    return structs, consts


def _origin(sk: FunctionSkeleton) -> str:
    where = f" @ {sk.entry}" if sk.entry else ""
    return f"Origine: {sk.original_name}{where} (confidenza: {sk.confidence})"


def _step_lines(sk: FunctionSkeleton, prefix: str) -> list[str]:
    lines = []
    for i, step in enumerate(sk.steps, 1):
        lines.append(f"{prefix}{i}. [{step.kind}] {_line(step.description)}")
        if step.todo:
            lines.append(f"{prefix}   TODO: {_line(step.todo)}")
    if sk.calls:
        lines.append(f"{prefix}Chiama: {', '.join(_line(c) for c in sk.calls)}")
    for q in sk.open_questions:
        lines.append(f"{prefix}DUBBIO: {_line(q)}")
    return lines


def _offset(offset: int | None) -> str:
    return f"+0x{offset:02x} " if offset is not None else ""


def _c_text(text: str | None) -> str:
    return _line(text).replace("*/", "* /")


def render_c(module: ScaffoldModule) -> dict[str, str]:
    lang = Language.C
    structs, consts = _unique_defs(module, lang)
    guard = f"{module.name.upper()}_H"

    h = [f"// {line}" for line in _banner(module)]
    h += ["", f"#ifndef {guard}", f"#define {guard}", ""]
    h += ["#include <stdbool.h>", "#include <stddef.h>", "#include <stdint.h>", ""]
    if consts:
        h.append("// --- Costanti ---")
        for name, c in consts.items():
            value = clean_number(c.value)
            desc = f"  // {_c_text(c.description)}" if c.description else ""
            if value is None:
                h.append(f"// TODO: {name} va estratto dal binario. {_c_text(c.description)}")
            else:
                h.append(f"#define {name} ({value}){desc}")
        h.append("")
    if structs:
        h.append("// --- Strutture ---")
        for name, s in structs.items():
            if s.description:
                h.append(f"// {_c_text(s.description)}")
            h.append(f"typedef struct {name} {{")
            for f in s.fields:
                ftype = clean_type(f.type, lang)
                note = _c_text(f"{_offset(f.offset)}{f.description}")
                h.append(
                    f"    {ftype} {identifier(f.name, lang, 'field')};"
                    + (f"  // {note}" if note else "")
                )
            if not s.fields:
                h.append("    uint8_t todo_fields;  // TODO: campi da dedurre")
            h.append(f"}} {name};")
            h.append("")

    c = [f"// {line}" for line in _banner(module)]
    c += ["", f'#include "{module.name}.h"', ""]

    if module.functions:
        h.append("// --- Funzioni ---")
    for sk in module.functions:
        ret = clean_type(sk.return_type, lang)
        params = (
            ", ".join(
                f"{clean_type(p.type, lang)} {identifier(p.name, lang, f'arg{i}')}"
                for i, p in enumerate(sk.parameters, 1)
            )
            or "void"
        )
        signature = f"{ret} {sk.name}({params})"
        h.append(f"{signature};")

        c.append("/**")
        c.append(f" * {_c_text(sk.summary)}")
        if sk.parameters:
            c.append(" *")
            for i, p in enumerate(sk.parameters, 1):
                pname = identifier(p.name, lang, f"arg{i}")
                c.append(f" * @param {pname} {_c_text(p.description)}".rstrip())
        if ret != "void" and sk.return_description:
            c.append(f" * @return {_c_text(sk.return_description)}")
        c.append(" *")
        c.append(f" * {_c_text(_origin(sk))}")
        c.append(" */")
        c.append(signature)
        c.append("{")
        c += [f"    // {line.replace('*/', '* /')}" for line in _step_lines(sk, "")]
        for i, p in enumerate(sk.parameters, 1):
            c.append(f"    (void){identifier(p.name, lang, f'arg{i}')};")
        c.append(f"    // TODO: implementa {sk.name}")
        if ret != "void":
            c.append(f"    {ret} todo_result = {{0}};")
            c.append("    return todo_result;")
        c.append("}")
        c.append("")

    h += ["", f"#endif  // {guard}"]
    return {f"{module.name}.h": "\n".join(h) + "\n", f"{module.name}.c": "\n".join(c)}


def _py_doc(text: str | None) -> str:
    return _line(text).replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def render_python(module: ScaffoldModule) -> dict[str, str]:
    lang = Language.PYTHON
    structs, consts = _unique_defs(module, lang)
    out = ['"""' + _py_doc(" ".join(_banner(module))) + '"""', ""]
    out += ["from __future__ import annotations", ""]
    out += ["from dataclasses import dataclass", "from typing import Any", ""]

    if consts:
        for name, c in consts.items():
            value = clean_number(c.value)
            desc = f"  # {_line(c.description)}" if c.description else ""
            if value is None:
                out.append(
                    f"{name}: Any = None  # TODO: estrarre dal binario. "
                    f"{_line(c.description)}".rstrip()
                )
            else:
                out.append(f"{name} = {value}{desc}")
        out.append("")
    for name, s in structs.items():
        out += ["", "@dataclass", f"class {name}:"]
        out.append(f'    """{_py_doc(s.description) or "TODO: descrivi la struttura."}"""')
        out.append("")
        for f in s.fields:
            note = _line(f"{_offset(f.offset)}{f.description}")
            out.append(
                f"    {identifier(f.name, lang, 'field')}: {clean_type(f.type, lang)}"
                + (f"  # {note}" if note else "")
            )
        if not s.fields:
            out.append("    pass  # TODO: campi da dedurre")
        out.append("")

    for sk in module.functions:
        params = ", ".join(
            f"{identifier(p.name, lang, f'arg{i}')}: {clean_type(p.type, lang)}"
            for i, p in enumerate(sk.parameters, 1)
        )
        ret = clean_type(sk.return_type, lang)
        out += ["", f"def {sk.name}({params}) -> {ret}:"]
        doc = [f'    """{_py_doc(sk.summary)}', ""]
        if sk.parameters:
            doc.append("    Args:")
            for i, p in enumerate(sk.parameters, 1):
                pname = identifier(p.name, lang, f"arg{i}")
                doc.append(f"        {pname}: {_py_doc(p.description)}".rstrip())
            doc.append("")
        if ret != "None":
            doc += ["    Returns:", f"        {_py_doc(sk.return_description)}".rstrip(), ""]
        doc += [f"    {_py_doc(_origin(sk))}", '    """']
        out += doc
        out += [f"    # {line}" for line in _step_lines(sk, "")]
        out.append(f'    raise NotImplementedError("TODO: implementa {sk.name}")')
        out.append("")
    return {f"{module.name}.py": "\n".join(out).rstrip() + "\n"}


def _rust_int_type(value: str) -> str:
    if "." in value:
        return "f64"
    if value.startswith("-"):
        return "i64"
    return "u32" if int(value, 0) <= 0xFFFFFFFF else "u64"


def render_rust(module: ScaffoldModule) -> dict[str, str]:
    lang = Language.RUST
    structs, consts = _unique_defs(module, lang)
    out = [f"//! {line}" for line in _banner(module)]
    out += ["", "#![allow(dead_code, unused_variables)]", ""]

    for name, c in consts.items():
        value = clean_number(c.value)
        if value is None:
            out.append(f"// TODO: {name} va estratto dal binario. {_line(c.description)}".rstrip())
            continue
        if c.description:
            out.append(f"/// {_line(c.description)}")
        out.append(f"pub const {name}: {_rust_int_type(value)} = {value};")
    if consts:
        out.append("")
    for name, s in structs.items():
        out.append(f"/// {_line(s.description) or 'TODO: descrivi la struttura.'}")
        out.append(f"pub struct {name} {{")
        for f in s.fields:
            note = _line(f"{_offset(f.offset)}{f.description}")
            if note:
                out.append(f"    /// {note}")
            out.append(f"    pub {identifier(f.name, lang, 'field')}: {clean_type(f.type, lang)},")
        if not s.fields:
            out.append("    // TODO: campi da dedurre")
        out += ["}", ""]

    for sk in module.functions:
        params = ", ".join(
            f"{identifier(p.name, lang, f'arg{i}')}: {clean_type(p.type, lang)}"
            for i, p in enumerate(sk.parameters, 1)
        )
        ret = clean_type(sk.return_type, lang)
        arrow = "" if ret in ("()", "") else f" -> {ret}"
        out.append(f"/// {_line(sk.summary)}")
        if sk.parameters:
            out.append("///")
            for i, p in enumerate(sk.parameters, 1):
                pname = identifier(p.name, lang, f"arg{i}")
                out.append(f"/// * `{pname}`: {_line(p.description)}".rstrip())
        if arrow and sk.return_description:
            out.append(f"///\n/// Ritorna: {_line(sk.return_description)}")
        out.append("///")
        out.append(f"/// {_origin(sk)}")
        out.append(f"pub fn {sk.name}({params}){arrow} {{")
        out += [f"    // {line}" for line in _step_lines(sk, "")]
        out.append(f'    todo!("implementa {sk.name}")')
        out += ["}", ""]
    return {f"{module.name}.rs": "\n".join(out).rstrip() + "\n"}


def render_notes(module: ScaffoldModule) -> str:
    rows = "\n".join(
        f"| `{sk.name}` | `{sk.original_name}` | {sk.entry or '-'} | {sk.confidence} | "
        f"{_line(sk.summary).replace('|', '/')} |"
        for sk in module.functions
    )
    questions = [f"- `{sk.name}`: {_line(q)}" for sk in module.functions for q in sk.open_questions]
    failed = [f"- `{name}`: {_line(err)}" for name, err in module.failed.items()]
    notes = [f"- {_line(n)}" for n in module.notes]
    return (
        f"# Scheletro: {module.name}\n\n" + "\n".join(_banner(module)) + "\n\n## Funzioni\n\n"
        "| Nome | Originale | Indirizzo | Confidenza | Cosa fa |\n"
        "|---|---|---|---|---|\n"
        f"{rows}\n\n"
        f"## Domande aperte\n\n{chr(10).join(questions) or '- nessuna'}\n\n"
        f"## Da controllare\n\n{chr(10).join(notes) or '- niente'}\n\n"
        f"## Funzioni non elaborate\n\n{chr(10).join(failed) or '- nessuna'}\n"
    )


_RENDERERS = {Language.C: render_c, Language.PYTHON: render_python, Language.RUST: render_rust}


def build_scaffold(module: ScaffoldModule) -> dict[str, str]:
    files = _RENDERERS[Language(module.language)](module)
    files["NOTE.md"] = render_notes(module)
    return files


def write_scaffold(module: ScaffoldModule, out_dir: Path) -> list[Path]:
    """Scrive lo scheletro in `out_dir`; non sovrascrive file già esistenti."""
    out_dir = Path(out_dir)
    files = build_scaffold(module)
    existing = [name for name in files if (out_dir / name).exists()]
    if existing:
        raise FileExistsError(
            f"In {out_dir} esistono già {', '.join(existing)}: scegli una cartella vuota."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in files.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
