from drdeconstruct import cli
from tests.conftest import FakeLLM


def test_cli_analyze_writes_json(tmp_path, monkeypatch, software_payload):
    monkeypatch.setattr(cli, "make_backend", lambda settings: FakeLLM(software_payload))
    src = tmp_path / "f.c"
    src.write_text("int f(int a)\n{\n  return a;\n}\n")
    out = tmp_path / "out.json"
    code = cli.main(["analyze", str(src), "--kind", "pseudocode_c", "-o", str(out)])
    assert code == 0
    assert "CRC32" in out.read_text()


def test_cli_reports_ambiguous(tmp_path, monkeypatch, software_payload, capsys):
    monkeypatch.setattr(cli, "make_backend", lambda settings: FakeLLM(software_payload))
    src = tmp_path / "x.txt"
    src.write_text("ab cd ef")
    assert cli.main(["analyze", str(src)]) == 1
    assert "Specifica" in capsys.readouterr().err


def test_cli_decompile_export_only(tmp_path, monkeypatch):
    from drdeconstruct.preprocess.ghidra import DecompiledFunction, DecompiledProgram

    prog = DecompiledProgram(
        program="fw.bin",
        language="MIPS:LE:32:default",
        functions=[DecompiledFunction("main", "00400000", 64, "int main(void){return 0;}")],
    )
    monkeypatch.setattr(cli.GhidraExporter, "export", lambda self, *a, **k: prog)
    binary = tmp_path / "fw.bin"
    binary.write_bytes(b"\x00")
    out = tmp_path / "out.c"
    assert cli.main(["decompile", str(binary), "-o", str(out)]) == 0
    assert "int main(void)" in out.read_text()


def test_cli_decompile_with_analysis(tmp_path, monkeypatch, software_payload):
    from drdeconstruct.preprocess.ghidra import DecompiledFunction, DecompiledProgram

    prog = DecompiledProgram(
        program="fw.bin",
        language="ARM:LE:32:v7",
        functions=[DecompiledFunction("sub_1", "1000", 40, "int sub_1(void){return 1;}")],
    )
    monkeypatch.setattr(cli.GhidraExporter, "export", lambda self, *a, **k: prog)
    monkeypatch.setattr(cli, "make_backend", lambda settings: FakeLLM(software_payload))
    binary = tmp_path / "fw.bin"
    binary.write_bytes(b"\x00")
    code = cli.main(["decompile", str(binary), "--analyze", "-o", str(tmp_path / "r.json")])
    assert code == 0
    assert "CRC32" in (tmp_path / "r.json").read_text()
