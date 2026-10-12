import json
import subprocess
from pathlib import Path

import pytest

from drdeconstruct.core.errors import DrDeconstructError
from drdeconstruct.preprocess.ghidra import (
    DecompiledProgram,
    GhidraExporter,
    find_analyze_headless,
)

EXPORT = {
    "program": "firmware.bin",
    "language": "MIPS:LE:32:default",
    "functions": [
        {
            "name": "FUN_00400100",
            "entry": "00400100",
            "size": 64,
            "code": "int FUN_00400100(void){return 1;}",
        },
        {"name": "main", "entry": "00400200", "size": 128, "code": "int main(void){return 0;}"},
    ],
}


def _fake_headless(tmp_path):
    hl = tmp_path / "analyzeHeadless"
    hl.write_text("#!/bin/sh\n")
    return hl


def _runner_writes(payload):
    def runner(cmd, **kwargs):
        # L'ultimo argomento prima dei flag numerici è il path di output JSON.
        out = Path(cmd[cmd.index("-postScript") + 2])
        out.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="esportate 2 funzioni", stderr="")

    return runner


def test_find_headless_requires_config(monkeypatch):
    monkeypatch.delenv("GHIDRA_INSTALL_DIR", raising=False)
    with pytest.raises(DrDeconstructError, match="GHIDRA_INSTALL_DIR"):
        find_analyze_headless()


def test_export_parses_functions(tmp_path):
    binary = tmp_path / "firmware.bin"
    binary.write_bytes(b"\x00" * 32)
    exporter = GhidraExporter(headless=_fake_headless(tmp_path), runner=_runner_writes(EXPORT))
    program = exporter.export(binary, processor="MIPS:LE:32:default")
    assert isinstance(program, DecompiledProgram)
    assert [f.name for f in program.functions] == ["FUN_00400100", "main"]
    assert program.arch == "MIPS:LE:32"
    assert "FUN_00400100 @ 00400100" in program.as_c_source()


def test_export_name_filter(tmp_path):
    binary = tmp_path / "firmware.bin"
    binary.write_bytes(b"\x00" * 32)
    exporter = GhidraExporter(headless=_fake_headless(tmp_path), runner=_runner_writes(EXPORT))
    program = exporter.export(binary, name_filter="^main$")
    assert [f.name for f in program.functions] == ["main"]


def test_command_includes_processor_for_raw_firmware(tmp_path):
    binary = tmp_path / "fw.bin"
    binary.write_bytes(b"\x00")
    exporter = GhidraExporter(headless=_fake_headless(tmp_path))
    cmd = exporter.command(binary, tmp_path, tmp_path / "o.json", 16, 500, "ARM:LE:32:v7", "0x8000")
    assert "-processor" in cmd and "ARM:LE:32:v7" in cmd
    assert "-loader-baseAddr" in cmd and "0x8000" in cmd
    assert "-deleteProject" in cmd


def test_export_missing_output_raises(tmp_path):
    binary = tmp_path / "fw.bin"
    binary.write_bytes(b"\x00")

    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="niente", stderr="")

    exporter = GhidraExporter(headless=_fake_headless(tmp_path), runner=runner)
    with pytest.raises(DrDeconstructError, match="export"):
        exporter.export(binary)


def test_export_rejects_missing_file(tmp_path):
    exporter = GhidraExporter(headless=_fake_headless(tmp_path))
    with pytest.raises(DrDeconstructError, match="non trovato"):
        exporter.export(tmp_path / "assente.bin")
