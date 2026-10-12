import io
import json
import subprocess

import pytest

from drdeconstruct.core.errors import BackendError
from drdeconstruct.llm.base import parse_json_into
from drdeconstruct.llm.claude_code import ClaudeCodeBackend
from drdeconstruct.llm.ollama import OllamaBackend
from drdeconstruct.software.schemas import SoftwareAnalysis


def test_parse_json_into_handles_fenced_and_wrapped(software_payload):
    text = "Ecco:\n```json\n" + json.dumps(software_payload) + "\n```\nfine"
    assert parse_json_into(text, SoftwareAnalysis).function_purpose.startswith("Calcola")


def test_parse_json_into_rejects_garbage():
    with pytest.raises(BackendError):
        parse_json_into("nessun json qui", SoftwareAnalysis)


def test_claude_code_runs_without_tools_or_api_key(monkeypatch, software_payload):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        out = json.dumps({"is_error": False, "result": "", "structured_output": software_payload})
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    result = ClaudeCodeBackend(runner=runner).structured("sys", "codice", SoftwareAnalysis)
    assert result.renames[0].proposed == "crc"
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--json-schema" in cmd and "-p" in cmd
    assert "ANTHROPIC_API_KEY" not in seen["kwargs"]["env"]
    assert seen["kwargs"]["input"] == "codice"


def test_claude_code_falls_back_to_result_text(software_payload):
    def runner(cmd, **kwargs):
        out = json.dumps({"is_error": False, "result": json.dumps(software_payload)})
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    assert ClaudeCodeBackend(runner=runner).structured("s", "u", SoftwareAnalysis)


def test_claude_code_missing_cli():
    def runner(cmd, **kwargs):
        raise FileNotFoundError

    with pytest.raises(BackendError, match="non trovata"):
        ClaudeCodeBackend(runner=runner).structured("s", "u", SoftwareAnalysis)


def test_ollama_sends_schema(software_payload):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        seen["body"] = json.loads(req.data)
        return Resp(json.dumps({"message": {"content": json.dumps(software_payload)}}).encode())

    result = OllamaBackend(opener=opener).structured("s", "u", SoftwareAnalysis)
    assert result.algorithm_notes
    assert seen["body"]["format"]["title"] == "SoftwareAnalysis"
    assert seen["body"]["stream"] is False


def test_find_claude_uses_native_installer_folder_when_path_is_stale(tmp_path, monkeypatch):
    from drdeconstruct.llm import claude_code

    monkeypatch.setattr(claude_code.sys, "platform", "win32")
    native = tmp_path / ".local" / "bin" / "claude.exe"
    native.parent.mkdir(parents=True)
    native.write_text("")
    assert claude_code.find_claude(lambda _: None, tmp_path) == str(native)
    assert claude_code.find_claude(lambda _: None, tmp_path / "altro") is None


def test_npm_shim_runs_node_directly(tmp_path):
    from drdeconstruct.llm.claude_code import claude_argv

    shim = tmp_path / "claude.cmd"
    shim.write_text("")
    # Senza lo script Node accanto resta lo shim.
    assert claude_argv(str(shim), lambda _: None) == [str(shim)]
    cli = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    assert claude_argv(str(shim), lambda _: "C:/node/node.exe") == ["C:/node/node.exe", str(cli)]
    assert claude_argv("/usr/bin/claude") == ["/usr/bin/claude"]
