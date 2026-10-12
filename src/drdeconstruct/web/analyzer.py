"""Modulo Web: mappa strutturale di una pagina -> spiegazione per reinterpretarla."""

from __future__ import annotations

from drdeconstruct.core.types import AnalysisRequest, ArtifactKind
from drdeconstruct.llm.base import LLMBackend
from drdeconstruct.web.extract import SiteSnapshot, build_snapshot
from drdeconstruct.web.prompts import SYSTEM, build_user_message
from drdeconstruct.web.schemas import WebAnalysis


class WebAnalyzer:
    kinds = frozenset({ArtifactKind.WEB_PAGE})

    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def analyze(self, req: AnalysisRequest) -> WebAnalysis:
        """Pagina HTML già salvata in locale: si analizza solo il file, senza rete."""
        snapshot = build_snapshot(req.source_name or "pagina-locale", req.content)
        return self.analyze_snapshot(snapshot, req.context)

    def analyze_snapshot(self, snapshot: SiteSnapshot, context: str = "") -> WebAnalysis:
        return self.llm.structured(SYSTEM, build_user_message(snapshot, context), WebAnalysis)
