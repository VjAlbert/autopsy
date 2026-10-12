"""Modelli dei dispositivi smart home individuati."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Ecosystem(str, Enum):
    XIAOMI = "xiaomi"
    AQARA = "aqara"
    TAPO = "tapo"
    VALETUDO = "valetudo"
    UNKNOWN = "unknown"


class Channel(str, Enum):
    BLE = "ble"
    MDNS = "mdns"
    MIIO = "miio"
    TAPO_UDP = "tapo_udp"


@dataclass
class SmartDevice:
    """Un dispositivo visto su un canale, con ciò che serve per collegarsi."""

    ecosystem: Ecosystem
    channel: Channel
    identifier: str
    name: str = ""
    model: str = ""
    address: str = ""
    needs: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)

    def key(self) -> str:
        """Chiave per unire lo stesso dispositivo visto su più canali."""
        mac = self.details.get("mac", "").lower().replace("-", ":")
        return mac or self.address or self.identifier

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ecosystem"] = self.ecosystem.value
        data["channel"] = self.channel.value
        return data

    def __str__(self) -> str:
        label = self.name or self.model or self.identifier
        where = f" @ {self.address}" if self.address else ""
        return f"[{self.ecosystem.value}/{self.channel.value}] {label}{where}"
