"""Modulo Hardware: spiega dump, registri e log di bus già acquisiti."""

from __future__ import annotations

from drdeconstruct.core.types import AnalysisRequest, ArtifactKind
from drdeconstruct.hardware.prompts import SYSTEM, build_user_message
from drdeconstruct.hardware.schemas import HardwareAnalysis
from drdeconstruct.llm.base import LLMBackend


class HardwareAnalyzer:
    kinds = frozenset({ArtifactKind.FLASH_DUMP, ArtifactKind.REGISTER_MAP, ArtifactKind.BUS_LOG})

    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def analyze(self, req: AnalysisRequest) -> HardwareAnalysis:
        return self.llm.structured(SYSTEM, build_user_message(req), HardwareAnalysis)
