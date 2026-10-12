"""Misura la qualità della rinomina su casi con i nomi veri noti.

Ogni caso (un file JSON in `eval_cases/`, incluso nel pacchetto) contiene pseudocodice in stile
Ghidra con nomi opachi e, per ogni simbolo, le parole accettabili nel nome
proposto. Il punteggio è la quota di simboli il cui nome proposto contiene
almeno una di quelle parole. I test usano un modello finto; `drdec eval` usa
quello vero e quindi consuma il tuo abbonamento o credito.

Chiavi di `expected`:
- `simbolo`: cercato prima nella mappa globale, poi nelle rinomine di qualsiasi
  funzione (utile per i casi con una sola funzione);
- `funzione/simbolo`: cercato solo nelle rinomine di quella funzione.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from drdeconstruct.core.types import AnalysisRequest, ArtifactKind
from drdeconstruct.preprocess.chunker import split_c_functions
from drdeconstruct.software.symbols import opaque_symbols

CASES_DIR = Path(__file__).parent / "eval_cases"

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True)
class EvalCase:
    name: str
    code: str
    expected: dict[str, list[str]]
    arch: str | None = None
    context: str = ""

    @classmethod
    def load(cls, path: Path) -> EvalCase:
        data = json.loads(path.read_text(encoding="utf-8"))
        code = data["code"]
        return cls(
            name=data.get("name", path.stem),
            code="\n".join(code) if isinstance(code, list) else code,
            expected=data["expected"],
            arch=data.get("arch"),
            context=data.get("context", ""),
        )


@dataclass
class CaseResult:
    name: str
    hits: list[str] = field(default_factory=list)
    misses: dict[str, str | None] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    consistency: float | None = None

    @property
    def score(self) -> float:
        total = len(self.hits) + len(self.misses)
        return len(self.hits) / total if total else 0.0


def tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[_\W]+", _CAMEL.sub("_", name).lower()) if t]


def name_matches(proposed: str | None, accepted: list[str]) -> bool:
    """Vero se un token del nome è una parola accettata o ne è l'estensione.

    `len` accetta `buf_len` e `length`; le parole di una o due lettere (come
    `i`) devono coincidere esattamente con un token.
    """
    if not proposed:
        return False
    toks = tokens(proposed)
    for word in (a.lower() for a in accepted):
        for t in toks:
            if t == word or (len(word) >= 3 and t.startswith(word)):
                return True
    return False


def _proposals(output: dict) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    globals_ = {k: v["proposed"] for k, v in output.get("symbol_map", {}).items()}
    per_function: dict[str, dict[str, str]] = {}
    for fn, result in output.get("functions", {}).items():
        per_function[fn] = {r["original"]: r["proposed"] for r in result.get("renames", [])}
    return globals_, per_function


def _lookup(key: str, globals_: dict[str, str], per_fn: dict[str, dict[str, str]]) -> str | None:
    if "/" in key:
        fn, sym = key.split("/", 1)
        return per_fn.get(fn, {}).get(sym)
    if key in globals_:
        return globals_[key]
    for renames in per_fn.values():
        if key in renames:
            return renames[key]
    return None


def consistency(case: EvalCase, output: dict) -> float | None:
    """Quota dei simboli opachi condivisi da più funzioni che hanno un solo nome.

    Con la mappa globale vale 1 per costruzione sui nomi sicuri; senza, misura
    quanto le analisi separate si contraddicono.
    """
    functions = split_c_functions(case.code)
    if len(functions) < 2:
        return None
    seen: dict[str, int] = {}
    for f in functions:
        for sym in opaque_symbols(f.code):
            seen[sym] = seen.get(sym, 0) + 1
    shared = [s for s, n in seen.items() if n > 1]
    if not shared:
        return None
    globals_, per_fn = _proposals(output)
    consistent = 0
    for sym in shared:
        if sym in globals_:
            consistent += 1
            continue
        names = {r[sym] for r in per_fn.values() if sym in r}
        consistent += len(names) <= 1
    return consistent / len(shared)


def score_case(case: EvalCase, output: dict) -> CaseResult:
    globals_, per_fn = _proposals(output)
    result = CaseResult(case.name)
    for fn, r in output.get("functions", {}).items():
        if r.get("refused"):
            result.refused.append(fn)
        elif "error" in r:
            result.errors.append(fn)
    for key, accepted in case.expected.items():
        proposed = _lookup(key, globals_, per_fn)
        if name_matches(proposed, accepted):
            result.hits.append(key)
        else:
            result.misses[key] = proposed
    result.consistency = consistency(case, output)
    return result


Analyze = Callable[[AnalysisRequest, list[tuple[str, str]]], dict]


def run_case(case: EvalCase, analyze: Analyze) -> CaseResult:
    """`analyze` è `cli.analyze_functions` già legato a orchestratore e motore."""
    functions = [(c.name, c.code) for c in split_c_functions(case.code)] or [(case.name, case.code)]
    base = AnalysisRequest(
        content="",
        kind=ArtifactKind.PSEUDOCODE_C,
        arch=case.arch,
        context=case.context,
        source_name=case.name,
    )
    return score_case(case, analyze(base, functions))


def load_cases(directory: Path = CASES_DIR) -> list[EvalCase]:
    return [EvalCase.load(p) for p in sorted(directory.glob("*.json"))]


def report(results: list[CaseResult]) -> str:
    lines = []
    hits = sum(len(r.hits) for r in results)
    total = hits + sum(len(r.misses) for r in results)
    for r in results:
        line = f"{r.name:<24} {r.score:6.0%}  ({len(r.hits)}/{len(r.hits) + len(r.misses)})"
        if r.consistency is not None:
            line += f"  coerenza {r.consistency:.0%}"
        if r.refused:
            line += f"  rifiutate: {', '.join(r.refused)}"
        if r.errors:
            line += f"  errori: {', '.join(r.errors)}"
        lines.append(line)
        for key, proposed in r.misses.items():
            lines.append(f"    mancato {key}: proposto {proposed or '(nessuno)'}")
    lines.append(f"{'TOTALE':<24} {hits / total if total else 0:6.0%}  ({hits}/{total})")
    return "\n".join(lines)
