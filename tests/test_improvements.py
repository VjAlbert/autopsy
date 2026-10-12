"""Rifiuti con modello di riserva, nomi coerenti tra funzioni, valutazione della rinomina."""

import json
import subprocess

import pytest

from drdeconstruct import cli
from drdeconstruct.core.errors import RefusalError
from drdeconstruct.evaluation import (
    CASES_DIR,
    EvalCase,
    load_cases,
    name_matches,
    run_case,
    score_case,
)
from drdeconstruct.llm.claude_code import ClaudeCodeBackend
from drdeconstruct.software.schemas import SoftwareAnalysis
from drdeconstruct.software.symbols import (
    GlobalName,
    SymbolMap,
    apply_symbol_map,
    build_symbol_map,
    opaque_symbols,
)

EVALS = CASES_DIR

PROGRAM = """void FUN_80001080(char param_1)
{
  do {
  } while ((_DAT_b8000c14 & 0x20) == 0);
  _DAT_b8000c00 = param_1;
  return;
}

void FUN_800010c0(char *param_1)
{
  for (; *param_1 != '\\0'; param_1 = param_1 + 1) {
    FUN_80001080(*param_1);
  }
  return;
}
"""


class SchemaLLM:
    """Motore finto che risponde in base allo schema richiesto."""

    name = "fake"

    def __init__(self, names: dict[str, tuple[str, str]], renames: dict[str, str] | None = None):
        self.names = names  # originale -> (proposto, confidence)
        self.renames = renames or {}
        self.calls: list[tuple[str, type]] = []

    def structured(self, system, user, schema):
        self.calls.append((user, schema))
        if schema is SymbolMap:
            wanted = user.split("Simboli da nominare: ", 1)[1].split("\n", 1)[0].split(", ")
            return SymbolMap(
                names=[
                    GlobalName(
                        original=s,
                        proposed=self.names[s][0],
                        kind="global",
                        rationale="test",
                        confidence=self.names[s][1],
                    )
                    for s in wanted
                    if s in self.names
                ]
            )
        renames = [
            {
                "original": o,
                "proposed": p,
                "kind": "variable",
                "rationale": "test",
                "confidence": "high",
            }
            for o, p in self.renames.items()
            if o in user
        ]
        return SoftwareAnalysis(
            function_purpose="test",
            control_flow=[],
            renames=renames,
            rewritten_code=user,
            algorithm_notes="",
            open_questions=[],
        )


def _proc(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")


# --- Rifiuti -----------------------------------------------------------------


def test_claude_code_retries_refusal_on_fallback_model(software_payload):
    models = []

    def runner(cmd, **kwargs):
        model = cmd[cmd.index("--model") + 1] if "--model" in cmd else None
        models.append(model)
        if model is None:
            return _proc({"is_error": False, "stop_reason": "refusal", "result": "no"})
        return _proc({"is_error": False, "structured_output": software_payload})

    backend = ClaudeCodeBackend(runner=runner, fallback_model="claude-opus-4-8")
    assert backend.structured("s", "u", SoftwareAnalysis).renames[0].proposed == "crc"
    assert models == [None, "claude-opus-4-8"]
    assert backend.last_model == "claude-opus-4-8"


def test_claude_code_refusal_from_safety_stops_without_fallback():
    def runner(cmd, **kwargs):
        return _proc({"is_error": False, "safety_stops": 1, "result": ""})

    with pytest.raises(RefusalError):
        ClaudeCodeBackend(runner=runner).structured("s", "u", SoftwareAnalysis)


def test_claude_code_reports_double_refusal():
    def runner(cmd, **kwargs):
        return _proc({"is_error": True, "stop_reason": "refusal", "result": "no"})

    backend = ClaudeCodeBackend(runner=runner, fallback_model="claude-opus-4-8")
    with pytest.raises(RefusalError, match="anche da claude-opus-4-8"):
        backend.structured("s", "u", SoftwareAnalysis)


def test_error_text_mentioning_refusal_is_not_a_refusal():
    def runner(cmd, **kwargs):
        return _proc({"is_error": True, "result": "connection refused"})

    with pytest.raises(Exception) as info:
        ClaudeCodeBackend(runner=runner, fallback_model="x").structured("s", "u", SoftwareAnalysis)
    assert not isinstance(info.value, RefusalError)


def test_api_backend_requests_server_side_fallbacks(monkeypatch, software_payload):
    pytest.importorskip("anthropic")
    from drdeconstruct.llm import anthropic_api

    seen = {}

    class Resp:
        stop_reason = "end_turn"
        stop_details = None
        usage = None
        model = "claude-opus-4-8"
        parsed_output = SoftwareAnalysis.model_validate(software_payload)

    class Messages:
        def parse(self, **kwargs):
            seen.update(kwargs)
            return Resp()

    backend = anthropic_api.AnthropicAPIBackend.__new__(anthropic_api.AnthropicAPIBackend)
    backend._client = type("C", (), {"beta": type("B", (), {"messages": Messages()})()})()
    backend.model, backend.effort = "claude-opus-5-5", "medium"
    assert backend.structured("s", "u", SoftwareAnalysis).algorithm_notes
    assert seen["fallbacks"] == "default"
    assert seen["betas"] == [anthropic_api.FALLBACK_BETA]
    assert backend.last_model == "claude-opus-4-8"


# --- Nomi coerenti -----------------------------------------------------------


def test_opaque_symbols_finds_ghidra_and_ida_names():
    assert opaque_symbols(PROGRAM) == [
        "FUN_80001080",
        "_DAT_b8000c14",
        "_DAT_b8000c00",
        "FUN_800010c0",
    ]
    assert opaque_symbols("byte_add = sub_401000();") == ["sub_401000"]


def test_symbol_map_keeps_only_requested_and_avoids_collisions():
    llm = SchemaLLM(
        {
            "FUN_80001080": ("param_1", "high"),  # collide con un identificatore esistente
            "_DAT_b8000c14": ("uart lsr", "high"),  # non valido come identificatore
            "_DAT_b8000c00": ("uart_thr", "low"),
        }
    )
    funcs = [("a", PROGRAM.split("\n\n")[0]), ("b", PROGRAM.split("\n\n")[1])]
    symbols = build_symbol_map(llm, funcs)
    assert symbols["FUN_80001080"].proposed == "param_1_2"
    assert symbols["_DAT_b8000c14"].proposed == "uart_lsr"
    assert "FUN_800010c0" not in symbols


def test_symbol_map_batches_share_decided_names():
    llm = SchemaLLM({"FUN_80001080": ("uart_putc", "high"), "_DAT_b8000c14": ("lsr", "high")})
    a, b = PROGRAM.split("\n\n")
    build_symbol_map(llm, [("a", a), ("b", b)], batch_chars=10)
    assert len(llm.calls) == 2
    second = llm.calls[1][0]
    assert "FUN_80001080 -> uart_putc" in second
    assert "Simboli da nominare: FUN_800010c0" in second


def test_apply_symbol_map_substitutes_confident_and_hints_low():
    symbols = {
        "_DAT_b8000c14": GlobalName(
            original="_DAT_b8000c14",
            proposed="uart_lsr",
            kind="global",
            rationale="",
            confidence="high",
        ),
        "_DAT_b8000c00": GlobalName(
            original="_DAT_b8000c00",
            proposed="uart_thr",
            kind="global",
            rationale="",
            confidence="low",
        ),
    }
    code, hints = apply_symbol_map(PROGRAM.split("\n\n")[0], symbols)
    assert "uart_lsr" in code and "_DAT_b8000c14" not in code
    assert "_DAT_b8000c00" in code
    assert [h.original for h in hints] == ["_DAT_b8000c00"]


def test_analyze_functions_runs_two_passes(tmp_path, monkeypatch, capsys):
    llm = SchemaLLM(
        {
            "FUN_80001080": ("uart_putc", "high"),
            "FUN_800010c0": ("uart_puts", "high"),
            "_DAT_b8000c14": ("uart_lsr", "high"),
            "_DAT_b8000c00": ("uart_thr", "medium"),
        }
    )
    monkeypatch.setattr(cli, "make_backend", lambda settings: llm)
    src = tmp_path / "p.c"
    src.write_text(PROGRAM)
    out = tmp_path / "r.json"
    assert cli.main(["analyze", str(src), "--kind", "pseudocode_c", "--split", "-o", str(out)]) == 0
    result = json.loads(out.read_text())
    assert result["symbol_map"]["FUN_80001080"]["proposed"] == "uart_putc"
    assert set(result["functions"]) == {"FUN_80001080", "FUN_800010c0"}
    # Nel secondo passaggio il codice arriva già con i nomi comuni.
    second_pass = [u for u, s in llm.calls if s is SoftwareAnalysis]
    assert all("FUN_80001080" not in u and "uart_putc" in u for u in second_pass)


def test_no_global_names_skips_first_pass(tmp_path, monkeypatch):
    llm = SchemaLLM({})
    monkeypatch.setattr(cli, "make_backend", lambda settings: llm)
    src = tmp_path / "p.c"
    src.write_text(PROGRAM)
    args = ["analyze", str(src), "--kind", "pseudocode_c", "--split", "--no-global-names"]
    assert cli.main([*args, "-o", str(tmp_path / "r.json")]) == 0
    assert all(s is SoftwareAnalysis for _, s in llm.calls)


# --- Valutazione -------------------------------------------------------------


def test_name_matches_tokens():
    assert name_matches("buf_len", ["len"])
    assert name_matches("dataLength", ["len"])
    assert name_matches("i", ["i"])
    assert not name_matches("index_ptr", ["i"])
    assert not name_matches(None, ["x"])


def test_bundled_cases_load_and_reference_real_symbols():
    cases = load_cases(EVALS)
    assert len(cases) >= 5
    for case in cases:
        for key in case.expected:
            assert key.split("/")[-1] in case.code, (case.name, key)


def test_eval_scores_and_measures_consistency():
    case = EvalCase(
        name="uart",
        code=PROGRAM,
        expected={
            "FUN_80001080": ["putc"],
            "_DAT_b8000c14": ["lsr"],
            "FUN_800010c0/param_1": ["s"],
        },
    )
    # Senza mappa globale le due funzioni danno nomi diversi alla stessa funzione.
    output = {
        "symbol_map": {},
        "functions": {
            "FUN_80001080": {"renames": [{"original": "FUN_80001080", "proposed": "uart_putc"}]},
            "FUN_800010c0": {
                "renames": [
                    {"original": "FUN_80001080", "proposed": "send_byte"},
                    {"original": "param_1", "proposed": "s"},
                ]
            },
        },
    }
    result = score_case(case, output)
    assert result.hits == ["FUN_80001080", "FUN_800010c0/param_1"]
    assert result.misses == {"_DAT_b8000c14": None}
    assert result.consistency == 0.0


def test_run_case_end_to_end_with_two_passes():
    case = EvalCase.load(EVALS / "uart_16550.json")
    llm = SchemaLLM(
        {
            "FUN_80001000": ("uart_init", "high"),
            "FUN_80001080": ("uart_putc", "high"),
            "FUN_800010c0": ("uart_puts", "high"),
            "DAT_80010000": ("uart_clock_hz", "high"),
            "_DAT_b8000c0c": ("uart_lcr", "high"),
            "_DAT_b8000c14": ("uart_lsr", "high"),
            "_DAT_b8000c00": ("uart_thr", "high"),
            "_DAT_b8000c04": ("uart_dlm", "high"),
        },
        renames={"param_1": "baud_rate"},
    )
    orch = cli.Orchestrator({cli.Domain.SOFTWARE: cli.SoftwareAnalyzer(llm)})
    result = run_case(case, lambda req, fns: cli.analyze_functions(orch, req, fns, llm=llm))
    assert result.consistency == 1.0
    assert "FUN_80001000/param_1" in result.hits
    assert result.misses == {"FUN_800010c0/param_1": "baud_rate"}
