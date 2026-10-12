"""Porting del codice sorgente dell'utente (Rust in primis), con Claude finto."""

import json
import shutil

import pytest

from drdeconstruct import cli, doctor
from drdeconstruct.core.errors import BackendError, DrDeconstructError
from drdeconstruct.software import port_source
from drdeconstruct.software.port import (
    Language,
    PortGenerator,
    camel_case,
    check_project,
    locate,
    parse_issues,
    plan_names,
    render_project,
    run_port,
    snake_case,
)
from drdeconstruct.software.port_source import (
    find_sources,
    from_text,
    guess_language,
    load_sources,
    split_units,
)

STATS_PY = '''"""Statistiche semplici."""

SCALE = 10


def addAll(xs):
    total = 0
    for x in xs:
        total += x
    return total


def mean(xs):
    return addAll(xs) / len(xs)
'''

ADD_ALL_RS = "pub fn add_all(xs: &[i64]) -> i64 {\n    xs.iter().sum()\n}"
MEAN_RS = "pub fn mean(xs: &[i64]) -> f64 {\n    add_all(xs) as f64 / xs.len() as f64\n}"


class SequenceLLM:
    """Restituisce le risposte nell'ordine; un'eccezione nella lista viene sollevata."""

    name = "fake"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def structured(self, system, user, schema):
        self.calls.append((system, user))
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        return schema.model_validate(item)


def unit(name, code, **extra):
    return {
        "original_name": name,
        "name": name,
        "code": code,
        "confidence": "high",
        "checklist": [
            {"kind": "test", "severity": "medium", "text": "Confronta con [1, 2, 3]."},
        ],
        **extra,
    }


@pytest.fixture
def big_stats(monkeypatch):
    """Forza la divisione in pezzi anche su un file piccolo."""
    monkeypatch.setattr(port_source, "SMALL_FILE_CHARS", 10)
    return from_text(STATS_PY, "python", "stats")


# --- Lettura del sorgente -------------------------------------------------


def test_small_files_are_translated_whole_but_names_are_known():
    files = from_text(STATS_PY, "python", "stats")
    assert [u.kind for u in files[0].units] == ["file"]
    assert files[0].symbols == ["addAll", "mean"]


def test_python_is_split_into_definitions_and_functions(big_stats):
    units = big_stats[0].units
    assert [(u.kind, u.name) for u in units] == [
        ("definitions", "definitions"),
        ("function", "addAll"),
        ("function", "mean"),
    ]
    assert "SCALE = 10" in units[0].code and "def" not in units[0].code
    assert units[1].lines == (6, 10)


def test_c_is_split_by_braces(monkeypatch):
    monkeypatch.setattr(port_source, "SMALL_FILE_CHARS", 10)
    src = "#include <stdint.h>\nstatic int k = 3;\n\nint add(int a, int b) {\n  return a + b;\n}\n"
    units = split_units(src, "c")
    assert [u.name for u in units] == ["definitions", "add"]
    assert units[1].lines == (4, 6)


def test_find_sources_skips_dependencies(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1\n")
    (tmp_path / "node_modules" / "lib").mkdir(parents=True)
    (tmp_path / "node_modules" / "lib" / "a.js").write_text("var a;\n")
    (tmp_path / "README.md").write_text("# no\n")
    assert [p.name for p in find_sources(tmp_path)] == ["main.py"]
    files = load_sources(tmp_path)
    assert files[0].path == "src/main.py" and files[0].language == "python"
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.txt").write_text("niente codice\n")
    with pytest.raises(DrDeconstructError, match="non ho trovato"):
        load_sources(tmp_path / "docs")


def test_guess_language():
    assert guess_language(STATS_PY) == "python"
    assert guess_language("package main\nfunc main() {}\n") == "go"
    assert guess_language("#include <stdio.h>\nint main(void) { return 0; }\n") == "c"


# --- Nomi -----------------------------------------------------------------


def test_names_are_idiomatic_and_unique():
    assert snake_case("addAll") == "add_all"
    assert snake_case("parseHTTPResponse") == "parse_http_response"
    assert camel_case("packet_header") == "PacketHeader"
    a = from_text("def doIt():\n    pass\n", "python", "a")
    b = from_text("class Parser:\n    pass\n\ndef do_it():\n    pass\n", "python", "b")
    names, notes = plan_names(a + b, Language.RUST)
    assert names == {"doIt": "do_it", "Parser": "Parser", "do_it": "do_it_2"}
    assert notes == []


# --- Traduzione -----------------------------------------------------------


def test_translates_unit_by_unit_with_shared_names(big_stats):
    llm = SequenceLLM(
        [
            unit("definitions", "pub const SCALE: i64 = 10;"),
            unit("addAll", ADD_ALL_RS.replace("add_all", "sum_all")),  # nome diverso
            unit("mean", MEAN_RS),
        ]
    )
    project = PortGenerator(llm).generate(big_stats, Language.RUST, name="stats")
    pf = project.files[0]
    assert [u.name for u in pf.units] == ["definitions", "add_all", "mean"]
    # il nome deciso prima vince e il codice viene allineato
    assert "pub fn add_all" in pf.units[1].code and "sum_all" not in pf.units[1].code
    # le funzioni ricevono le definizioni già tradotte e la mappa dei nomi
    _, user = llm.calls[2]
    assert "pub const SCALE: i64 = 10;" in user and "- addAll -> add_all" in user
    assert "Linguaggio sorgente: Python" in user


def test_one_failure_does_not_stop_the_rest_and_placeholders_are_flagged(big_stats):
    llm = SequenceLLM(
        [
            unit("definitions", "pub const SCALE: i64 = 10;"),
            BackendError("timeout"),
            unit("mean", 'pub fn mean(xs: &[i64]) -> f64 {\n    todo!("dopo")\n}'),
        ]
    )
    project = PortGenerator(llm).generate(big_stats, Language.RUST)
    pf = project.files[0]
    assert pf.failed == {"addAll": "timeout"}
    assert pf.units[-1].checklist[0].severity == "high"
    assert "segnaposto" in pf.units[-1].checklist[0].text


def test_stop_keeps_what_is_ready(big_stats):
    state = {"stop": False}

    class StoppingLLM(SequenceLLM):
        def structured(self, system, user, schema):
            state["stop"] = True
            return super().structured(system, user, schema)

    llm = StoppingLLM([unit("definitions", "pub const SCALE: i64 = 10;")])
    project = PortGenerator(llm).generate(
        big_stats, Language.RUST, should_stop=lambda: state["stop"]
    )
    assert len(llm.calls) == 1
    assert "Interrotto" in project.notes[-1]


# --- Rendering e controllo ------------------------------------------------


def _project(big_stats, **extra):
    llm = SequenceLLM(
        [
            unit("definitions", "pub const SCALE: i64 = 10;", **extra),
            unit("addAll", ADD_ALL_RS),
            unit("mean", MEAN_RS),
        ]
    )
    return PortGenerator(llm).generate(big_stats, Language.RUST, name="my-stats")


def test_rust_project_layout(big_stats):
    project = _project(big_stats, imports=["use std::fmt;"], dependencies=['regex = "1"', "strano"])
    files, spans = render_project(project)
    assert set(files) == {"Cargo.toml", "src/lib.rs", "src/stats.rs", "CHECKLIST.md"}
    assert 'name = "my_stats"' in files["Cargo.toml"]
    assert (
        'regex = "1"' in files["Cargo.toml"] and "# da controllare: strano" in files["Cargo.toml"]
    )
    assert "pub mod stats;\npub use stats::*;" in files["src/lib.rs"]
    text = files["src/stats.rs"]
    assert text.count("use std::fmt;") == 1 and "use crate::*;" not in text
    lines = text.splitlines()
    line = next(i for i, t in enumerate(lines, 1) if "add_all(xs) as f64" in t)
    assert locate(spans, "src/stats.rs", line) == (0, 2)
    assert locate(spans, "src\\stats.rs", line) == (0, 2)  # percorsi Windows


def test_parse_compiler_output():
    out = (
        "src/stats.rs:12:5: error[E0425]: cannot find value `y` in this scope\n"
        "src/stats.rs:3:1: warning: unused\n"
        "stats.c:4:9: error: expected ';' before '}' token\n"
    )
    issues = parse_issues(out)
    assert [(i.file, i.line) for i in issues] == [("src/stats.rs", 12), ("stats.c", 4)]


def test_run_port_fixes_compiler_errors(big_stats, tmp_path):
    broken = MEAN_RS.replace("add_all(xs)", "add_al(xs)")
    llm = SequenceLLM(
        [
            unit("definitions", "pub const SCALE: i64 = 10;"),
            unit("addAll", ADD_ALL_RS),
            unit("mean", broken),
            unit("mean", MEAN_RS, checklist=[]),  # correzione
        ]
    )
    calls = []

    def runner(cmd, cwd):
        calls.append(cmd)
        text = (cwd / "src" / "stats.rs").read_text()
        if "add_al(" in text:
            line = next(i for i, t in enumerate(text.splitlines(), 1) if "add_al(" in t)
            return 101, f"src/stats.rs:{line}:5: error[E0425]: cannot find function `add_al`\n"
        return 0, ""

    out = tmp_path / "out"
    project, paths = run_port(
        llm, big_stats, out, "rust", name="stats", which=lambda n: "/bin/cargo", runner=runner
    )
    assert calls[0][:2] == ["cargo", "check"] and len(calls) == 2
    assert project.compile_ok is True and project.fixed_units == ["stats.py: mean"]
    _, fix_user = llm.calls[3]
    assert "cannot find function `add_al`" in fix_user and "def mean" in fix_user
    assert "add_al(" not in (out / "src" / "stats.rs").read_text()
    checklist = (out / "CHECKLIST.md").read_text(encoding="utf-8")
    assert "✓ `cargo check` senza errori" in checklist
    # la checklist della prima traduzione non si perde con la correzione
    assert checklist.count("Confronta con [1, 2, 3]") == 3


def test_errors_left_after_the_last_round_go_in_the_checklist(big_stats, tmp_path):
    llm = SequenceLLM(
        [
            unit("definitions", "pub const SCALE: i64 = 10;"),
            unit("addAll", ADD_ALL_RS),
            unit("mean", MEAN_RS),
        ]
    )

    def runner(cmd, cwd):
        return 101, "src/stats.rs:9:1: error[E0308]: mismatched types\n"

    out = tmp_path / "out"
    project, _ = run_port(
        llm, big_stats, out, "rust", fix_rounds=0, which=lambda n: "cargo", runner=runner
    )
    assert project.compile_ok is False and project.compile_issues[0].unit == "addAll"
    assert "mismatched types" in (out / "CHECKLIST.md").read_text(encoding="utf-8")


def test_checker_that_cannot_start_is_a_note_not_a_crash(big_stats, tmp_path):
    llm = SequenceLLM([unit("definitions", "x"), unit("addAll", "y"), unit("mean", "z")])
    project, _ = run_port(
        llm,
        big_stats,
        tmp_path / "out",
        "rust",
        which=lambda n: "cargo",
        runner=lambda cmd, cwd: (101, "failed to download crate"),
    )
    assert project.compiler is None and "non è riuscito" in project.notes[-1]


def test_no_compiler_means_unchecked(big_stats, tmp_path):
    llm = SequenceLLM([unit("definitions", "x"), unit("addAll", "y"), unit("mean", "z")])
    project, _ = run_port(llm, big_stats, tmp_path / "out", "rust", which=lambda n: None)
    assert project.compiler is None
    assert "Non controllata" in (tmp_path / "out" / "CHECKLIST.md").read_text(encoding="utf-8")


def test_python_target_is_checked_in_process(tmp_path):
    files = {"a.py": "def f(:\n    pass\n", "CHECKLIST.md": ""}
    tool, ok, issues, _ = check_project(tmp_path, files, Language.PYTHON)
    assert tool == "compile()" and ok is False and issues[0].file == "a.py"


def test_refuses_non_empty_folder(big_stats, tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    with pytest.raises(DrDeconstructError, match="non è vuota"):
        run_port(SequenceLLM([]), big_stats, tmp_path, "rust")


@pytest.mark.skipif(shutil.which("cargo") is None, reason="Rust non installato")
def test_real_cargo_check_on_generated_project(tmp_path, monkeypatch):
    monkeypatch.setattr(port_source, "SMALL_FILE_CHARS", 10)
    a = from_text("def helper():\n    return 1\n", "python", "alpha")
    b = from_text("def useHelper():\n    return helper() + 1\n", "python", "beta")
    llm = SequenceLLM(
        [
            unit("helper", "pub fn helper() -> i32 {\n    1\n}"),
            unit("useHelper", "pub fn use_helper() -> i32 {\n    helper() + 1\n}"),
        ]
    )
    project, _ = run_port(llm, a + b, tmp_path / "out", "rust", name="two")
    # due moduli che si chiamano a vicenda tramite `use crate::*`
    assert project.compiler == "cargo check" and project.compile_ok is True


# --- CLI e controllo del sistema ---------------------------------------


def test_cli_port(monkeypatch, tmp_path, capsys):
    src = tmp_path / "stats.py"
    src.write_text(STATS_PY)
    llm = SequenceLLM([unit("stats", ADD_ALL_RS + "\n\n" + MEAN_RS)])
    monkeypatch.setattr(cli, "make_backend", lambda s: llm)
    out = tmp_path / "out"
    code = cli.main(["port", str(src), "--out", str(out), "--no-check", "--backend", "ollama"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["language"] == "rust" and data["files"][0]["source"] == "stats.py"
    assert (out / "Cargo.toml").exists() and (out / "CHECKLIST.md").exists()


def test_doctor_reports_rust():
    assert doctor.check_rust(lambda n: "/bin/cargo").ok
    missing = doctor.check_rust(lambda n: None)
    assert not missing.ok and missing.optional and missing.link == doctor.RUST_DOWNLOAD
