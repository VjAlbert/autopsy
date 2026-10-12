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
