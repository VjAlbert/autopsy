"""Controllo del sistema e risultati leggibili per la GUI."""

import io
import json

from drdeconstruct import doctor
from drdeconstruct.config import Settings
from drdeconstruct.report import analysis_markdown, to_markdown


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(payload):
    def open_(url, timeout):
        assert url.endswith("/api/tags") and timeout <= 5
        return _Resp(json.dumps(payload).encode())

    return open_


def _refused(url, timeout):
    raise ConnectionRefusedError("refused")


def test_claude_code_check():
    ok = doctor.check_claude_code(lambda name: "/usr/bin/claude")
    assert ok.ok and "Accedi a Claude" in ok.fix
    missing = doctor.check_claude_code(lambda name: None)
    assert not missing.ok and missing.link == doctor.CLAUDE_DOCS and missing.symbol == "✗"


def test_ollama_check_explains_model_and_service():
    host, model = "http://localhost:11434", "qwen2.5-coder:14b"
    assert doctor.check_ollama(host, model, _opener({"models": [{"name": model}]})).ok
    no_model = doctor.check_ollama(host, model, _opener({"models": []}))
    assert not no_model.ok and f"ollama pull {model}" in no_model.fix
    down = doctor.check_ollama(host, model, _refused)
    assert not down.ok and "Non risponde" in down.detail


def test_ghidra_check(tmp_path):
    missing = doctor.check_ghidra({}, lambda n: None)
    assert not missing.ok and missing.optional and missing.symbol == "○"
    support = tmp_path / "support"
    support.mkdir()
    for name in ("analyzeHeadless", "analyzeHeadless.bat"):
        (support / name).write_text("")
    no_java = doctor.check_ghidra({"GHIDRA_INSTALL_DIR": str(tmp_path)}, lambda n: None)
    assert not no_java.ok and "Java 21" in no_java.detail
    ready = doctor.check_ghidra({"GHIDRA_INSTALL_DIR": str(tmp_path)}, lambda n: "/bin/java")
    assert ready.ok


def test_run_checks_puts_the_chosen_engine_first():
    checks = doctor.run_checks(Settings(backend="ollama"), {}, lambda n: None, _refused)
    assert [c.key for c in checks] == ["ollama", "ghidra", "flashrom", "rust"]
    text = doctor.format_checks(checks)
    assert "✗ Ollama" in text and "→" in text


def test_terminal_commands_per_platform():
    assert doctor.login_command("win32")[-1] == "claude"
    assert doctor.CLAUDE_INSTALL_WINDOWS in doctor.install_command("win32")
    assert "osascript" in doctor.login_command("darwin")


def test_cli_doctor(monkeypatch, capsys):
    from drdeconstruct import cli

    monkeypatch.setattr(doctor, "run_checks", lambda s: [doctor.Check("x", "Prova", True, "ok")])
    assert cli.main(["doctor"]) == 0
    assert "✓ Prova: ok" in capsys.readouterr().out


def test_software_result_is_readable(software_payload):
    text = analysis_markdown(software_payload)
    assert "## Cosa fa" in text and "## Nomi proposti" in text
    assert "| Nome originale |" in text and "```c" in text
    assert "{" not in text.split("```")[0]  # niente JSON prima del codice


def test_multi_function_result_and_failures():
    result = {
        "symbol_map": {
            "FUN_1": {
                "original": "FUN_1",
                "proposed": "uart_putc",
                "kind": "function",
                "rationale": "scrive su THR",
                "confidence": "high",
            }
        },
        "functions": {
            "FUN_1": {"summary": "Scrive un byte", "open_questions": []},
            "FUN_2": {"error": "cyber", "refused": True},
        },
    }
    text = to_markdown(result)
    assert "| FUN_1 | uart_putc | alta |" in text
    assert "## Funzione FUN_2" in text and "il modello si è rifiutato" in text
    assert "_nessuno_" in text
