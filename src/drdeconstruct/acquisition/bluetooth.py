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


BLUETOOTH_UNAVAILABLE = (
    "Il Bluetooth non risponde: controlla che sia acceso nelle impostazioni del computer "
    "e che il PC abbia un adattatore Bluetooth. Su Windows serve Windows 10 o successivo."
)


def run_ble(coro_factory):
    """Esegue un lavoro bleak e traduce i suoi errori in un messaggio comprensibile."""
    bleak = _require_bleak()
    try:
        return asyncio.run(coro_factory(bleak))
    except DrDeconstructError:
        raise
    except Exception as exc:  # bleak usa eccezioni diverse per ogni sistema operativo
        if isinstance(exc, (OSError, bleak.exc.BleakError)) or "bluetooth" in str(exc).lower():
            raise DrDeconstructError(f"{BLUETOOTH_UNAVAILABLE} (dettaglio: {exc})") from exc
        raise


def scan_ble(timeout: float = 8.0) -> list[DeviceInfo]:
    """Elenca i dispositivi BLE in ascolto nelle vicinanze."""

    async def _scan(bleak):
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

    return run_ble(_scan)


def read_services(address: str) -> dict[str, list[str]]:
    """Si collega a un dispositivo BLE e ne elenca servizi e caratteristiche."""

    async def _read(bleak):
        async with bleak.BleakClient(address) as client:
            result: dict[str, list[str]] = {}
            for service in client.services:
                result[service.uuid] = [c.uuid for c in service.characteristics]
            return result

    return run_ble(_read)
