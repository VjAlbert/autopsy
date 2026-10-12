"""Orchestratore: instrada ogni richiesta al modulo di dominio giusto."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from pydantic import BaseModel

from drdeconstruct.core import detect
from drdeconstruct.core.errors import AmbiguousInputError
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind, Domain

CONFIDENCE_THRESHOLD = 0.8


class Analyzer(Protocol):
    kinds: frozenset[ArtifactKind]

    def analyze(self, req: AnalysisRequest) -> BaseModel: ...


class Orchestrator:
    def __init__(self, analyzers: dict[Domain, Analyzer]):
        self.analyzers = analyzers

    def resolve(self, req: AnalysisRequest) -> AnalysisRequest:
        """Completa dominio e tipo: prima ciò che dichiara l'operatore, poi l'euristica."""
        if req.kind is not None:
            domain = req.domain or req.kind.domain
            if domain != req.kind.domain:
                raise AmbiguousInputError(
                    f"Il tipo {req.kind.value} appartiene al dominio {req.kind.domain.value}, "
                    f"non a {domain.value}."
                )
            return replace(req, domain=domain)

        g = detect.guess(req.content, req.source_name)
        if req.domain is not None and g.kind.domain != req.domain:
            raise AmbiguousInputError(
                f"Dominio {req.domain.value} dichiarato ma l'euristica suggerisce {g}: "
                "specifica --kind."
            )
        if g.confidence < CONFIDENCE_THRESHOLD:
            raise AmbiguousInputError(
                f"Tipo di input incerto (ipotesi: {g}). Specifica --domain e --kind."
            )
        return replace(req, domain=g.kind.domain, kind=g.kind)

    def run(self, req: AnalysisRequest) -> BaseModel:
        req = self.resolve(req)
        assert req.domain is not None and req.kind is not None
        analyzer = self.analyzers.get(req.domain)
        if analyzer is None:
            raise AmbiguousInputError(f"Nessun modulo registrato per {req.domain.value}.")
        if req.kind not in analyzer.kinds:
            raise AmbiguousInputError(
                f"Il modulo {req.domain.value} non gestisce il tipo {req.kind.value}."
            )
        return analyzer.analyze(req)
