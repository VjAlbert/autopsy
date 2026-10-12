"""Lettura del codice sorgente da tradurre: file, linguaggio e pezzi.

Il porting lavora un pezzo alla volta: ogni funzione di primo livello è un
pezzo, il resto del file (tipi, costanti, import, variabili globali) è il
pezzo "definitions" e fa anche da contesto per le funzioni. Dove il
linguaggio non si divide in modo affidabile (classi Java/C#, Go con metodi,
file piccoli) il file intero è un solo pezzo.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from drdeconstruct.core.errors import DrDeconstructError
from drdeconstruct.preprocess.chunker import split_c_functions

# Estensione -> linguaggio sorgente.
EXTENSIONS = {
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".cs": "csharp",
    ".go": "go",
    ".kt": "kotlin",
    ".swift": "swift",
    ".php": "php",
    ".rb": "ruby",
    ".rs": "rust",
    ".pas": "pascal",
    ".vb": "vbnet",
    ".lua": "lua",
}

# Cartelle da non leggere mai: dipendenze, build, ambienti virtuali.
SKIP_DIRS = frozenset(
    ".git .hg .svn node_modules __pycache__ .venv venv env build dist target bin obj "
    ".idea .vscode .mypy_cache .pytest_cache .tox vendor".split()
)

# Linguaggi in cui le funzioni di primo livello si separano contando le graffe.
_BRACE = frozenset({"c", "cpp", "javascript", "typescript", "php"})

# Sotto questa dimensione il file si traduce intero: più contesto, meno chiamate.
SMALL_FILE_CHARS = 2500
# Sopra questa dimensione un pezzo è a rischio di traduzione incompleta.
LARGE_UNIT_CHARS = 15000
# Quanto del pezzo "definitions" passare come contesto a ogni funzione.
CONTEXT_CHARS = 4000


@dataclass(frozen=True)
class SourceUnit:
    name: str
    kind: str  # "function", "definitions" o "file"
    code: str
    lines: tuple[int, int] | None = None


@dataclass
class SourceFile:
    path: str  # relativo alla radice scelta
    language: str
    text: str
    units: list[SourceUnit] = field(default_factory=list)
    # Funzioni definite nel file, anche quando il file si traduce intero.
    symbols: list[str] = field(default_factory=list)

    @property
    def definitions(self) -> str:
        for u in self.units:
            if u.kind == "definitions":
                return u.code
        return ""


def detect_language(path: str | Path) -> str | None:
    return EXTENSIONS.get(Path(path).suffix.lower())


def find_sources(root: str | Path, limit: int = 500) -> list[Path]:
    """I file sorgente sotto `root` (o `root` stesso), saltando dipendenze e build."""
    root = Path(root)
    if root.is_file():
        return [root]
    if not root.is_dir():
        raise DrDeconstructError(f"{root} non esiste.")
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel[:-1]):
            continue
        if path.is_file() and detect_language(path):
            found.append(path)
            if len(found) >= limit:
                break
    return found


def _python_units(text: str) -> list[SourceUnit] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    lines = text.splitlines()
    units, used = [], set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        end = node.end_lineno or node.lineno
        units.append(
            SourceUnit(node.name, "function", "\n".join(lines[start - 1 : end]), (start, end))
        )
        used.update(range(start, end + 1))
    rest = "\n".join(line for i, line in enumerate(lines, 1) if i not in used).strip()
    return _with_definitions(units, rest)


def _brace_units(text: str) -> list[SourceUnit]:
    lines = text.splitlines()
    units, used, cursor = [], set(), 0
    for chunk in split_c_functions(text):
        first = chunk.code.splitlines()[0]
        start = next((i for i in range(cursor, len(lines)) if lines[i] == first), cursor)  # 0-based
        end = start + len(chunk.code.splitlines()) - 1
        cursor = end + 1
        units.append(SourceUnit(chunk.name, "function", chunk.code, (start + 1, end + 1)))
        used.update(range(start, end + 1))
    rest = "\n".join(line for i, line in enumerate(lines) if i not in used).strip()
    return _with_definitions(units, rest)


def _with_definitions(units: list[SourceUnit], rest: str) -> list[SourceUnit]:
    if not units:
        return []
    meaningful = [
        line
        for line in rest.splitlines()
        if line.strip() and not line.strip().startswith(("#!", "//", "#", "/*", "*", '"""'))
    ]
    if meaningful:
        units.insert(0, SourceUnit("definitions", "definitions", rest))
    return units


def _split(text: str, language: str) -> list[SourceUnit]:
    if language == "python":
        return _python_units(text) or []
    if language in _BRACE:
        return _brace_units(text)
    return []


def split_units(text: str, language: str, name: str = "file") -> list[SourceUnit]:
    """Divide un file in pezzi da tradurre uno alla volta."""
    whole = [SourceUnit(name, "file", text, (1, len(text.splitlines())))]
    if len(text) <= SMALL_FILE_CHARS:
        return whole
    return _split(text, language) or whole


# Metodo Java/C#: modificatori, tipo di ritorno, nome, parentesi (sulla stessa riga).
_METHOD = r"^[ \t]*(?:(?:{})[ \t]+)+[\w<>\[\], \t]+?[ \t]+(\w+)[ \t]*\([^;\n]*$"

_DEFINED = {
    "go": r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(",
    "rust": r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)",
    "java": _METHOD.format("public|private|protected|static|final|synchronized"),
    "csharp": _METHOD.format("public|private|protected|internal|static|async|override|virtual"),
    "kotlin": r"^\s*(?:\w+\s+)*fun\s+(\w+)",
    "swift": r"^\s*(?:\w+\s+)*func\s+(\w+)",
    "ruby": r"^\s*def\s+(?:self\.)?(\w+[?!]?)",
    "lua": r"^\s*(?:local\s+)?function\s+(?:[\w.]+[.:])?(\w+)",
}


def defined_names(text: str, language: str) -> list[str]:
    """Le funzioni definite in un file, per dare loro un nome di destinazione."""
    names = [u.name for u in _split(text, language) if u.kind == "function"]
    pattern = _DEFINED.get(language)
    if pattern:
        names += re.findall(pattern, text, re.M)
    keywords = {"if", "for", "while", "switch", "catch", "return", "new", "main"}
    return [n for n in dict.fromkeys(names) if n not in keywords]


def _source_file(path: str, language: str, text: str, name: str) -> SourceFile:
    return SourceFile(
        path, language, text, split_units(text, language, name), defined_names(text, language)
    )


def load_sources(root: str | Path) -> list[SourceFile]:
    """Legge file o cartella e prepara i pezzi da tradurre."""
    root = Path(root)
    base = root.parent if root.is_file() else root
    files = []
    for path in find_sources(root):
        language = detect_language(path) or "text"
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        rel = path.relative_to(base).as_posix()
        files.append(_source_file(rel, language, text, path.stem))
    if not files:
        raise DrDeconstructError(
            f"In {root} non ho trovato codice sorgente da tradurre "
            f"(estensioni riconosciute: {', '.join(sorted(set(EXTENSIONS)))})."
        )
    return files


def from_text(text: str, language: str, name: str = "codice") -> list[SourceFile]:
    """Codice incollato a mano: un solo file virtuale."""
    if not text.strip():
        raise DrDeconstructError("Non c'è codice da tradurre.")
    filename = f"{name}{_ext(language)}"
    return [_source_file(filename, language, text, name)]


def _ext(language: str) -> str:
    for ext, lang in EXTENSIONS.items():
        if lang == language:
            return ext
    return ".txt"


def guess_language(text: str) -> str:
    """Indovina il linguaggio di un testo incollato (euristica semplice)."""
    try:
        ast.parse(text)
        if re.search(r"^\s*(def|class|import|from)\s", text, re.M):
            return "python"
    except SyntaxError:
        pass
    checks = [
        ("go", r"^\s*package\s+\w+|^\s*func\s+(\(\w+ \*?\w+\)\s*)?\w+\("),
        ("rust", r"^\s*(pub\s+)?fn\s+\w+|^\s*use\s+\w+::"),
        ("java", r"^\s*(public|private)\s+(static\s+)?class\s+\w+|System\.out\.print"),
        ("csharp", r"^\s*using\s+System|^\s*namespace\s+\w+"),
        ("typescript", r":\s*(string|number|boolean)\b.*[=;)]|^\s*interface\s+\w+\s*\{"),
        ("javascript", r"^\s*(function\s+\w+|const\s+\w+\s*=|let\s+\w+|module\.exports)"),
        ("php", r"<\?php"),
        ("cpp", r"#include\s*<(iostream|vector|string)>|std::|::\w+\(|\bclass\s+\w+\s*[:{]"),
        ("c", r"#include\s*[<\"]|\b(int|void|char)\s+\w+\s*\("),
    ]
    for language, pattern in checks:
        if re.search(pattern, text, re.M):
            return language
    return "c"


SOURCE_LANGUAGE_LABELS = {
    "c": "C",
    "cpp": "C++",
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "csharp": "C#",
    "go": "Go",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "php": "PHP",
    "ruby": "Ruby",
    "rust": "Rust",
    "pascal": "Pascal",
    "vbnet": "VB.NET",
    "lua": "Lua",
}
