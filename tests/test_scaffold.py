import ast
import json
import shutil
import subprocess

import pytest

from drdeconstruct import cli
from drdeconstruct.core.errors import BackendError
from drdeconstruct.software.scaffold import (
    Language,
    ScaffoldGenerator,
    SourceFunction,
    build_scaffold,
    clean_number,
    clean_type,
    identifier,
    write_scaffold,
)
from drdeconstruct.software.scaffold_schemas import FunctionSkeleton

CRC_SRC = """int FUN_00401a20(byte *p1,int p2){
  uint v1 = 0xffffffff;
  int i;
  for (i = 0; i < p2; i++) { v1 = v1 >> 8 ^ DAT_00405000[(v1 ^ p1[i]) & 0xff]; }
  return ~v1;
}

int FUN_00401b00(int *p1){
  return FUN_00401a20(p1 + 2, *p1);
}
"""

TYPES = {
    "c": {"u32": "uint32_t", "buf": "const uint8_t *", "len": "size_t", "hdr": "const Packet *"},
    "python": {"u32": "int", "buf": "bytes", "len": "int", "hdr": "Packet"},
    "rust": {"u32": "u32", "buf": "&[u8]", "len": "usize", "hdr": "&Packet"},
}


def skeleton_payloads(lang: str) -> list[dict]:
    t = TYPES[lang]
    crc = {
        "original_name": "FUN_00401a20",
        "name": "crc32-update",  # va normalizzato
        "confidence": "high",
        "summary": "Calcola il CRC-32 IEEE di un buffer.",
        "parameters": [
            {"name": "buf", "type": t["buf"], "description": "dati"},
            {"name": "len", "type": t["len"], "description": "lunghezza in byte"},
        ],
        "return_type": t["u32"],
        "return_description": "CRC complementato",
        "steps": [
            {"kind": "init", "description": "accumulatore a 0xFFFFFFFF"},
            {
                "kind": "loop",
                "description": "per ogni byte aggiorna con la tabella",
                "todo": "usa CRC32_TABLE",
            },
            {"kind": "return", "description": "restituisce il complemento */ fine"},
        ],
        "constants": [
            {"name": "CRC32_POLY", "value": "0xEDB88320u", "description": "polinomio riflesso"},
            {"name": "CRC32_TABLE", "value": None, "description": "256 voci a DAT_00405000"},
        ],
        "calls": [],
        "open_questions": ["La tabella è generata a runtime?"],
    }
    packet = {
        "original_name": "FUN_00401b00",
        "name": "packet_checksum",
        "confidence": "medium",
        "summary": "Calcola il CRC del payload di un pacchetto con FUN_00401a20.",
        "parameters": [{"name": "packet", "type": t["hdr"], "description": "pacchetto"}],
        "return_type": t["u32"],
        "steps": [{"kind": "call", "description": "chiama FUN_00401a20 sul payload"}],
        "structs": [
            {
                "name": "Packet",
                "description": "Intestazione + payload",
                "fields": [
                    {"name": "length", "type": t["u32"], "offset": 0, "description": "byte"},
                    {"name": "type", "type": t["u32"], "offset": 4},
                ],
            }
        ],
        "constants": [{"name": "CRC32_POLY", "value": "0x04C11DB7"}],
        "calls": ["FUN_00401a20"],
    }
    return [crc, packet]


class SequenceLLM:
    """Motore finto che restituisce una risposta diversa a ogni chiamata."""

    name = "fake"

    def __init__(self, payloads: list):
        self.payloads = list(payloads)
        self.calls = []

    def structured(self, system, user, schema):
        self.calls.append((system, user, schema))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return schema.model_validate(payload)


FUNCS = [
    SourceFunction("FUN_00401a20", "int FUN_00401a20(...) {...}", "00401a20"),
    SourceFunction("FUN_00401b00", "int FUN_00401b00(...) {...}", "00401b00"),
]


def generate(lang: str):
    llm = SequenceLLM(skeleton_payloads(lang))
    module = ScaffoldGenerator(llm).generate(FUNCS, Language(lang), source="fw.bin", arch="x86")
    return module, llm


def test_names_are_made_consistent_across_functions():
    module, llm = generate("c")
    crc, packet = module.functions
    assert crc.name == "crc32_update" and crc.entry == "00401a20"
    # i riferimenti al nome originale puntano al nuovo nome
    assert packet.calls == ["crc32_update"]
    assert "crc32_update" in packet.summary and "FUN_00401a20" not in packet.steps[0].description
    # la seconda chiamata conosce già il nome assegnato alla prima
    _, second_user, schema = llm.calls[1]
    assert "FUN_00401a20 -> crc32_update" in second_user and schema is FunctionSkeleton
    # la costante con due definizioni diverse viene segnalata
    assert any("CRC32_POLY" in n for n in module.notes)


def test_backend_error_does_not_stop_other_functions():
    payloads = [BackendError("timeout"), skeleton_payloads("c")[1]]
    module = ScaffoldGenerator(SequenceLLM(payloads)).generate(FUNCS)
    assert [f.name for f in module.functions] == ["packet_checksum"]
    assert module.failed == {"FUN_00401a20": "timeout"}
    assert "timeout" in build_scaffold(module)["NOTE.md"]


def test_duplicate_names_get_suffix():
    a, b = skeleton_payloads("c")
    b["name"] = "crc32_update"
    module = ScaffoldGenerator(SequenceLLM([a, b])).generate(FUNCS)
    assert [f.name for f in module.functions] == ["crc32_update", "crc32_update_2"]


def test_helpers():
    assert identifier("1st value", Language.C) == "_1st_value"
    assert identifier("return", Language.RUST) == "return_"
    assert identifier("class", Language.PYTHON) == "class_"
    assert clean_number("0x10UL") == "0x10" and clean_number("007") == "7"
    assert clean_number("tabella") is None
    assert clean_type("uint8_t *", Language.C) == "uint8_t *"
    assert clean_type('int); system("x"', Language.C) == "intptr_t"
    assert clean_type("list[int", Language.PYTHON) == "Any"
    assert clean_type("Vec<u8", Language.RUST) == "usize"


def test_c_scaffold_compiles(tmp_path):
    module, _ = generate("c")
    files = build_scaffold(module)
    assert set(files) == {"fw.h", "fw.c", "NOTE.md"}
    src = files["fw.c"]
    assert "uint32_t crc32_update(const uint8_t * buf, size_t len)" in src
    assert "TODO: usa CRC32_TABLE" in src and "Origine: FUN_00401a20 @ 00401a20" in src
    assert "* /" in src  # il commento non viene chiuso dal testo del modello
    assert "#define CRC32_POLY (0xEDB88320)" in files["fw.h"]
    assert "TODO: CRC32_TABLE va estratto" in files["fw.h"]
    assert "DAT_00405000" not in src  # nessun corpo copiato
    if not shutil.which("gcc"):
        pytest.skip("gcc non disponibile")
    write_scaffold(module, tmp_path)
    proc = subprocess.run(
        ["gcc", "-std=c99", "-Wall", "-Werror", "-fsyntax-only", str(tmp_path / "fw.c")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_python_scaffold_parses():
    module, _ = generate("python")
    src = build_scaffold(module)["fw.py"]
    ast.parse(src)
    assert "def crc32_update(buf: bytes, len: int) -> int:" in src
    assert "class Packet:" in src and "CRC32_TABLE: Any = None" in src
    assert 'raise NotImplementedError("TODO: implementa crc32_update")' in src


def test_rust_scaffold_compiles(tmp_path):
    module, _ = generate("rust")
    files = build_scaffold(module)
    src = files["fw.rs"]
    assert "pub fn crc32_update(buf: &[u8], len: usize) -> u32 {" in src
    assert "pub const CRC32_POLY: u32 = 0xEDB88320;" in src
    if not shutil.which("rustc"):
        pytest.skip("rustc non disponibile")
    write_scaffold(module, tmp_path)
    proc = subprocess.run(
        [
            "rustc",
            "--edition",
            "2021",
            "--crate-type",
            "lib",
            "--emit",
            "metadata",
            "-o",
            str(tmp_path / "fw.rmeta"),
            str(tmp_path / "fw.rs"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_write_scaffold_refuses_overwrite(tmp_path):
    module, _ = generate("c")
    (tmp_path / "fw.c").write_text("mio codice")
    with pytest.raises(FileExistsError):
        write_scaffold(module, tmp_path)
    assert (tmp_path / "fw.c").read_text() == "mio codice"


def test_cli_scaffold_splits_functions(tmp_path, monkeypatch):
    llm = SequenceLLM(skeleton_payloads("python"))
    monkeypatch.setattr(cli, "make_backend", lambda settings: llm)
    src = tmp_path / "crc.c"
    src.write_text(CRC_SRC)
    out = tmp_path / "out"
    assert cli.main(["scaffold", str(src), "--out", str(out), "--lang", "python"]) == 0
    assert len(llm.calls) == 2
    assert "<code>\nint FUN_00401a20" in llm.calls[0][1]
    assert sorted(p.name for p in out.iterdir()) == ["NOTE.md", "crc.py"]


def test_cli_scaffold_refuses_non_empty_dir_before_calling_model(tmp_path, monkeypatch, capsys):
    llm = SequenceLLM([])
    monkeypatch.setattr(cli, "make_backend", lambda settings: llm)
    src = tmp_path / "crc.c"
    src.write_text(CRC_SRC)
    out = tmp_path / "out"
    out.mkdir()
    (out / "x.txt").write_text("")
    assert cli.main(["scaffold", str(src), "--out", str(out)]) == 1
    assert llm.calls == [] and "non è vuota" in capsys.readouterr().err


def test_cli_decompile_with_scaffold(tmp_path, monkeypatch):
    from drdeconstruct.preprocess.ghidra import DecompiledFunction, DecompiledProgram

    prog = DecompiledProgram(
        program="fw.bin",
        language="x86:LE:32:default",
        functions=[DecompiledFunction(f.name, f.entry, 64, f.code) for f in FUNCS],
    )
    monkeypatch.setattr(cli.GhidraExporter, "export", lambda self, *a, **k: prog)
    monkeypatch.setattr(cli, "make_backend", lambda settings: SequenceLLM(skeleton_payloads("c")))
    binary = tmp_path / "fw.bin"
    binary.write_bytes(b"\x00")
    out = tmp_path / "skel"
    code = cli.main(["decompile", str(binary), "--scaffold", str(out), "-o", str(tmp_path / "x")])
    assert code == 0
    assert "crc32_update" in (out / "fw.c").read_text()
    assert "Origine: FUN_00401b00 @ 00401b00" in (out / "fw.c").read_text()


def test_module_plan_is_json_serialisable():
    module, _ = generate("c")
    data = json.loads(module.model_dump_json())
    assert data["language"] == "c" and data["functions"][0]["name"] == "crc32_update"
