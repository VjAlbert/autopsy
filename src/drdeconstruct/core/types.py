"""Tipi di dominio condivisi tra orchestratore, analizzatori e CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Domain(str, Enum):
    SOFTWARE = "software"
    HARDWARE = "hardware"
    WEB = "web"


class ArtifactKind(str, Enum):
    PSEUDOCODE_C = "pseudocode_c"
    ASSEMBLY = "assembly"
    FLASH_DUMP = "flash_dump"
    REGISTER_MAP = "register_map"
    BUS_LOG = "bus_log"
    WEB_PAGE = "web_page"

    @property
    def domain(self) -> Domain:
        if self in (ArtifactKind.PSEUDOCODE_C, ArtifactKind.ASSEMBLY):
            return Domain.SOFTWARE
        if self is ArtifactKind.WEB_PAGE:
            return Domain.WEB
        return Domain.HARDWARE


@dataclass(frozen=True)
class AnalysisRequest:
    """Una richiesta di analisi.

    `domain` e `kind` sono dichiarati dall'operatore; l'euristica di
    `core.detect` interviene solo se mancano.
    """

    content: str
    domain: Domain | None = None
    kind: ArtifactKind | None = None
    arch: str | None = None
    context: str = ""
    source_name: str | None = None
    extra: dict[str, str] = field(default_factory=dict)
