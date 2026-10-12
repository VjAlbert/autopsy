import pytest

from drdeconstruct.core.errors import AmbiguousInputError
from drdeconstruct.core.orchestrator import Orchestrator
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind, Domain
from drdeconstruct.hardware.analyzer import HardwareAnalyzer
from drdeconstruct.software.analyzer import SoftwareAnalyzer
from drdeconstruct.software.schemas import SoftwareAnalysis
from tests.conftest import FakeLLM

CRC = """int FUN_00401a20(byte *p1,int p2){
  uint v1 = 0xffffffff;
  int i;
  for (i = 0; i < p2; i++) { v1 = v1 >> 8 ^ DAT_00405000[(v1 ^ p1[i]) & 0xff]; }
  return ~v1;
}"""


def make(payload):
    llm = FakeLLM(payload)
    orch = Orchestrator(
        {Domain.SOFTWARE: SoftwareAnalyzer(llm), Domain.HARDWARE: HardwareAnalyzer(llm)}
    )
    return orch, llm


def test_declared_kind_routes_to_software(software_payload):
    orch, llm = make(software_payload)
    result = orch.run(AnalysisRequest(CRC, kind=ArtifactKind.PSEUDOCODE_C, arch="x86"))
    assert isinstance(result, SoftwareAnalysis)
    assert result.renames[0].proposed == "crc"
    _, user, _ = llm.calls[0]
    assert "<code>" in user and "x86" in user


def test_domain_kind_mismatch_is_rejected(software_payload):
    orch, _ = make(software_payload)
    with pytest.raises(AmbiguousInputError):
        orch.run(AnalysisRequest(CRC, domain=Domain.HARDWARE, kind=ArtifactKind.PSEUDOCODE_C))


def test_ambiguous_input_asks_operator(software_payload):
    orch, llm = make(software_payload)
    with pytest.raises(AmbiguousInputError):
        orch.run(AnalysisRequest("12 34 56 78 de ad be ef"))
    assert llm.calls == []


def test_extension_fallback(software_payload):
    orch, _ = make(software_payload)
    req = orch.resolve(AnalysisRequest(CRC, source_name="dump_funzione.c"))
    assert req.kind is ArtifactKind.PSEUDOCODE_C and req.domain is Domain.SOFTWARE
