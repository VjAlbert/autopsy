"""Modulo Software: pseudocodice/ASM -> spiegazione e rinomina semantica."""

from __future__ import annotations

from drdeconstruct.core.types import AnalysisRequest, ArtifactKind
from drdeconstruct.llm.base import LLMBackend
from drdeconstruct.software.prompts import SYSTEM, build_user_message
from drdeconstruct.software.schemas import SoftwareAnalysis


class SoftwareAnalyzer:
    kinds = frozenset({ArtifactKind.PSEUDOCODE_C, ArtifactKind.ASSEMBLY})

    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def analyze(self, req: AnalysisRequest) -> SoftwareAnalysis:
        return self.llm.structured(SYSTEM, build_user_message(req), SoftwareAnalysis)
