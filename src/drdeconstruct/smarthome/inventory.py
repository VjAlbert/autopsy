"""Inventario unico dei dispositivi visti su tutti i canali."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from drdeconstruct.core.errors import DrDeconstructError
from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice

Scanner = Callable[[], list[SmartDevice]]


@dataclass
class Inventory:
    devices: list[SmartDevice] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"devices": [d.to_dict() for d in self.devices], "errors": self.errors}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> Inventory:
        """Ricostruisce un inventario salvato (GUI «Salva elenco» o `drdec home scan -o`)."""
        devices = [
            SmartDevice(
                ecosystem=Ecosystem(d["ecosystem"]),
                channel=Channel(d["channel"]),
                identifier=d["identifier"],
                name=d.get("name", ""),
                model=d.get("model", ""),
                address=d.get("address", ""),
                needs=list(d.get("needs", [])),
                details=dict(d.get("details", {})),
            )
            for d in data["devices"]
        ]
        return cls(devices, dict(data.get("errors", {})))


def merge(devices: list[SmartDevice]) -> list[SmartDevice]:
    """Unisce lo stesso dispositivo visto su più canali (stesso MAC o indirizzo)."""
    merged: dict[str, SmartDevice] = {}
    for dev in devices:
        key = dev.key()
        first = merged.get(key)
        if first is None:
            merged[key] = dev
            continue
        channels = first.details.get("channels", first.channel.value).split(",")
        if dev.channel.value not in channels:
            channels.append(dev.channel.value)
        first.details = {**dev.details, **first.details, "channels": ",".join(channels)}
        first.needs += [n for n in dev.needs if n not in first.needs]
        first.name = first.name or dev.name
        first.model = first.model or dev.model
        if first.ecosystem.value == "unknown":
            first.ecosystem = dev.ecosystem
    return list(merged.values())


def build_inventory(scanners: dict[str, Scanner]) -> Inventory:
    """Esegue ogni scansione; un canale che fallisce non ferma gli altri."""
    inv = Inventory()
    found: list[SmartDevice] = []
    for name, scan in scanners.items():
        try:
            found.extend(scan())
        except (DrDeconstructError, OSError) as exc:
            inv.errors[name] = str(exc)
    inv.devices = merge(found)
    return inv


def default_scanners(
    timeout: float = 4.0, ble: bool = True, lan: bool = True
) -> dict[str, Scanner]:
    from drdeconstruct.smarthome import ble as ble_mod
    from drdeconstruct.smarthome import mdns, miio, tapo

    scanners: dict[str, Scanner] = {}
    if ble:
        scanners["ble"] = lambda: ble_mod.scan(timeout=timeout * 2)
    if lan:
        scanners["mdns"] = lambda: mdns.discover(timeout=timeout)
        scanners["miio"] = lambda: miio.discover(timeout=timeout)
        scanners["tapo"] = lambda: tapo.discover(timeout=timeout)
    return scanners
