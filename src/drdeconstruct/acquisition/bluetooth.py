"""Scansione dei dispositivi Bluetooth LE vicini e lettura dei loro servizi.

Usa bleak (extra opzionale). Serve per i dispositivi che espongono dati via
BLE; la Yi cam tipicamente non rientra, ma altri dispositivi sì.
"""

from __future__ import annotations

import asyncio

from drdeconstruct.acquisition.models import DeviceInfo, LinkKind
from drdeconstruct.core.errors import DrDeconstructError


def _require_bleak():
    try:
        import bleak
    except ImportError as exc:
        raise DrDeconstructError(
            "Installa l'extra hardware: pip install 'drdeconstruct[hardware]'"
        ) from exc
    return bleak


def scan_ble(timeout: float = 8.0) -> list[DeviceInfo]:
    """Elenca i dispositivi BLE in ascolto nelle vicinanze."""
    bleak = _require_bleak()

    async def _scan():
        found = await bleak.BleakScanner.discover(timeout=timeout)
        return [
            DeviceInfo(
                kind=LinkKind.BLUETOOTH,
                identifier=d.address,
                label=d.name or "(senza nome)",
                details={"rssi": str(getattr(d, "rssi", ""))},
            )
            for d in found
        ]

    return asyncio.run(_scan())


def read_services(address: str) -> dict[str, list[str]]:
    """Si collega a un dispositivo BLE e ne elenca servizi e caratteristiche."""
    bleak = _require_bleak()

    async def _read():
        async with bleak.BleakClient(address) as client:
            result: dict[str, list[str]] = {}
            for service in client.services:
                result[service.uuid] = [c.uuid for c in service.characteristics]
            return result

    return asyncio.run(_read())
