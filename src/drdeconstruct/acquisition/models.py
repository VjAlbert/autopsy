"""Modelli dei dati scambiati con i dispositivi collegati."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LinkKind(str, Enum):
    USB = "usb"
    SERIAL = "serial"
    BLUETOOTH = "bluetooth"


@dataclass(frozen=True)
class DeviceInfo:
    """Un dispositivo individuato, in forma leggibile."""

    kind: LinkKind
    identifier: str
    label: str
    details: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.kind.value}] {self.label} ({self.identifier})"


@dataclass(frozen=True)
class MemoryImage:
    """Un'immagine di memoria letta da un dispositivo, con i suoi metadati."""

    data: bytes
    source: str
    sha256: str

    @property
    def size(self) -> int:
        return len(self.data)
