"""Scoperta dei servizi annunciati via mDNS/Zeroconf sulla rete locale.

Molti dispositivi si annunciano da soli: i Xiaomi WiFi con `_miio._udp`, gli hub
Aqara come accessori HomeKit (`_hap._tcp`), i robot con Valetudo con
`_valetudo._tcp`, i dispositivi Matter con `_matter._tcp`. Si ascolta soltanto.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from drdeconstruct.core.errors import DrDeconstructError
from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice

SERVICE_TYPES = (
    "_miio._udp.local.",
    "_hap._tcp.local.",
    "_valetudo._tcp.local.",
    "_matter._tcp.local.",
    "_aqara._tcp.local.",
    "_aqara-setup._tcp.local.",
)


@dataclass
class MdnsRecord:
    service_type: str
    name: str
    addresses: list[str] = field(default_factory=list)
    port: int = 0
    properties: dict[str, str] = field(default_factory=dict)


def _ecosystem(record: MdnsRecord) -> Ecosystem:
    text = " ".join([record.name, *record.properties.values()]).lower()
    if record.service_type.startswith("_valetudo"):
        return Ecosystem.VALETUDO
    if record.service_type.startswith("_aqara") or "aqara" in text or "lumi" in text:
        return Ecosystem.AQARA
    if record.service_type.startswith("_miio") or any(
        w in text
        for w in ("xiaomi", "mijia", "roborock", "dreame", "yeelight", "zhimi", "chuangmi")
    ):
        return Ecosystem.XIAOMI
    if "tapo" in text or "tp-link" in text:
        return Ecosystem.TAPO
    return Ecosystem.UNKNOWN


def _needs(record: MdnsRecord, ecosystem: Ecosystem) -> list[str]:
    stype = record.service_type
    if ecosystem is Ecosystem.VALETUDO:
        return ["nessuna: API REST locale di Valetudo (http://<ip>/api/v2/robot)"]
    if stype.startswith("_miio"):
        return ["token miIO del dispositivo"]
    if stype.startswith("_hap"):
        return ["abbinamento HomeKit (codice a 8 cifre sul dispositivo o sull'hub)"]
    if stype.startswith("_matter"):
        return ["dispositivo Matter già messo in servizio: serve un controller Matter"]
    return ["canale da approfondire con la guida"]


def to_device(record: MdnsRecord) -> SmartDevice:
    ecosystem = _ecosystem(record)
    short = record.name.split("." + record.service_type.split(".")[0])[0]
    details = {"service": record.service_type, "port": str(record.port), **record.properties}
    return SmartDevice(
        ecosystem=ecosystem,
        channel=Channel.MDNS,
        identifier=record.name,
        name=short,
        model=record.properties.get("md", ""),
        address=record.addresses[0] if record.addresses else "",
        needs=_needs(record, ecosystem),
        details=details,
    )


def browse_zeroconf(timeout: float = 4.0) -> list[MdnsRecord]:
    """Ascolta gli annunci mDNS con la libreria zeroconf (extra smarthome)."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError as exc:
        raise DrDeconstructError(
            "Installa l'extra smarthome: pip install 'drdeconstruct[smarthome]'"
        ) from exc

    seen: set[tuple[str, str]] = set()

    class _Listener:
        def add_service(self, zc, type_, name):
            seen.add((type_, name))

        def update_service(self, zc, type_, name):
            seen.add((type_, name))

        def remove_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, list(SERVICE_TYPES), _Listener())
        time.sleep(timeout)
        records = []
        for type_, name in sorted(seen):
            info = zc.get_service_info(type_, name, timeout=1500)
            if info is None:
                records.append(MdnsRecord(type_, name))
                continue
            props = {
                k.decode(errors="replace"): (v or b"").decode(errors="replace")
                for k, v in (info.properties or {}).items()
            }
            records.append(MdnsRecord(type_, name, info.parsed_addresses(), info.port or 0, props))
        return records
    finally:
        zc.close()


def discover(
    timeout: float = 4.0, browser: Callable[[float], list[MdnsRecord]] = browse_zeroconf
) -> list[SmartDevice]:
    return [to_device(r) for r in browser(timeout)]
