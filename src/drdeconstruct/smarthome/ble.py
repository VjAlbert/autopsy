"""Riconoscimento dei dispositivi Xiaomi, Aqara e Tapo dagli annunci Bluetooth LE.

Gli annunci si leggono senza collegarsi al dispositivo. Xiaomi e Aqara usano il
formato MiBeacon (service data UUID 0xFE95): quando non è cifrato contiene già
temperatura, umidità, batteria e simili; quando è cifrato serve la "bindkey"
del dispositivo, che si ottiene dal cloud Xiaomi e qui non viene gestita.
"""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice

MIBEACON_UUID = "0000fe95-0000-1000-8000-00805f9b34fb"
XIAOMI_COMPANY_ID = 0x038F

# Elenco parziale di product id MiBeacon noti.
MIBEACON_PRODUCTS = {
    0x0098: "HHCCJCY01 (Flower Care)",
    0x01AA: "LYWSDCGQ (termoigrometro)",
    0x045B: "LYWSD02 (orologio termoigrometro)",
    0x055B: "LYWSD03MMC (termoigrometro)",
    0x0347: "CGG1 (termoigrometro Qingping)",
    0x0576: "CGD1 (sveglia Qingping)",
    0x066F: "CGDK2 (termoigrometro Qingping)",
    0x0A83: "CGDN1 (monitor aria Qingping)",
    0x0863: "RTCGQ02LM (sensore movimento Aqara)",
    0x098B: "MCCGQ02HL (sensore porta Xiaomi)",
    0x07F6: "MJYD02YL-A (luce notturna)",
}

# Tipi di oggetto MiBeacon in chiaro: (nome, decodifica dei byte)
_OBJECTS: dict[int, tuple[str, Callable[[bytes], object]]] = {
    0x1004: ("temperature_c", lambda b: struct.unpack("<h", b[:2])[0] / 10),
    0x1006: ("humidity_pct", lambda b: struct.unpack("<H", b[:2])[0] / 10),
    0x1007: ("illuminance_lux", lambda b: int.from_bytes(b[:3], "little")),
    0x1008: ("moisture_pct", lambda b: b[0]),
    0x1009: ("conductivity_us_cm", lambda b: struct.unpack("<H", b[:2])[0]),
    0x100A: ("battery_pct", lambda b: b[0]),
    0x100D: (
        "temperature_humidity",
        lambda b: {
            "temperature_c": struct.unpack("<h", b[:2])[0] / 10,
            "humidity_pct": struct.unpack("<H", b[2:4])[0] / 10,
        },
    ),
    0x1010: ("formaldehyde_mg_m3", lambda b: struct.unpack("<H", b[:2])[0] / 100),
    0x1018: ("light", lambda b: b[0]),
    0x1019: ("door_open", lambda b: b[0] == 0),
    0x000F: ("motion_with_light", lambda b: int.from_bytes(b[:3], "little")),
}


@dataclass
class MiBeacon:
    product_id: int
    version: int
    encrypted: bool
    frame_counter: int
    mac: str = ""
    readings: dict[str, object] = field(default_factory=dict)

    @property
    def product(self) -> str:
        return MIBEACON_PRODUCTS.get(self.product_id, f"product id 0x{self.product_id:04X}")


def parse_mibeacon(data: bytes) -> MiBeacon | None:
    """Decodifica un payload MiBeacon; restituisce None se è troppo corto."""
    if len(data) < 5:
        return None
    frame_ctrl, product_id, counter = struct.unpack_from("<HHB", data, 0)
    beacon = MiBeacon(
        product_id=product_id,
        version=(frame_ctrl >> 12) & 0x0F,
        encrypted=bool(frame_ctrl & 0x0008),
        frame_counter=counter,
    )
    pos = 5
    if frame_ctrl & 0x0010:  # MAC incluso, in ordine inverso
        if len(data) < pos + 6:
            return beacon
        beacon.mac = ":".join(f"{b:02X}" for b in reversed(data[pos : pos + 6]))
        pos += 6
    if frame_ctrl & 0x0020:  # byte di capability
        pos += 1
        if len(data) > pos - 1 and data[pos - 1] & 0x20:  # capability I/O estesa
            pos += 2
    if beacon.encrypted or not frame_ctrl & 0x0040:
        return beacon
    while pos + 3 <= len(data):
        obj_type, length = struct.unpack_from("<HB", data, pos)
        value = data[pos + 3 : pos + 3 + length]
        pos += 3 + length
        if len(value) < length:
            break
        decoder = _OBJECTS.get(obj_type)
        if decoder is None:
            beacon.readings[f"0x{obj_type:04X}"] = value.hex()
            continue
        name, fn = decoder
        try:
            decoded = fn(value)
        except (IndexError, struct.error):
            decoded = value.hex()
        if isinstance(decoded, dict):
            beacon.readings.update(decoded)
        else:
            beacon.readings[name] = decoded
    return beacon


@dataclass
class Advertisement:
    """Ciò che serve di un annuncio BLE, indipendente dalla libreria usata."""

    address: str
    name: str = ""
    rssi: int | None = None
    service_data: dict[str, bytes] = field(default_factory=dict)
    manufacturer_data: dict[int, bytes] = field(default_factory=dict)
    service_uuids: list[str] = field(default_factory=list)


def _ecosystem_from_name(name: str) -> Ecosystem | None:
    lowered = name.lower()
    if "aqara" in lowered or lowered.startswith("lumi"):
        return Ecosystem.AQARA
    if lowered.startswith(("tapo", "tp-link", "tplink")):
        return Ecosystem.TAPO
    if lowered.startswith(("mi ", "mijia", "xiaomi", "roborock", "dreame", "viomi", "yeelight")):
        return Ecosystem.XIAOMI
    return None


def identify(adv: Advertisement) -> SmartDevice | None:
    """Riconosce un dispositivo dei tre ecosistemi; None se non c'entra."""
    payload = adv.service_data.get(MIBEACON_UUID)
    by_name = _ecosystem_from_name(adv.name)
    details: dict[str, str] = {}
    if adv.rssi is not None:
        details["rssi"] = str(adv.rssi)

    if payload is not None:
        beacon = parse_mibeacon(payload)
        if beacon is None:
            return None
        ecosystem = by_name if by_name is Ecosystem.AQARA else Ecosystem.XIAOMI
        needs = []
        if beacon.encrypted:
            needs.append("bindkey MiBeacon (dal cloud Xiaomi) per leggere i valori cifrati")
        details.update(
            {"mibeacon_version": str(beacon.version), "encrypted": str(beacon.encrypted)}
        )
        if beacon.mac:
            details["mac"] = beacon.mac
        for key, value in beacon.readings.items():
            details[key] = str(value)
        return SmartDevice(
            ecosystem=ecosystem,
            channel=Channel.BLE,
            identifier=adv.address,
            name=adv.name,
            model=beacon.product,
            address=adv.address,
            needs=needs,
            details=details,
        )

    if XIAOMI_COMPANY_ID in adv.manufacturer_data or by_name is not None:
        ecosystem = by_name or Ecosystem.XIAOMI
        needs = []
        if ecosystem is Ecosystem.TAPO:
            needs.append("dispositivo in modalità abbinamento; il controllo avviene poi via WiFi")
        else:
            needs.append("BLE usato per l'abbinamento; il controllo avviene via WiFi (miIO)")
        return SmartDevice(
            ecosystem=ecosystem,
            channel=Channel.BLE,
            identifier=adv.address,
            name=adv.name,
            address=adv.address,
            needs=needs,
            details=details,
        )
    return None


def identify_all(ads: Iterable[Advertisement]) -> list[SmartDevice]:
    return [d for d in (identify(a) for a in ads) if d is not None]


def scan_advertisements(timeout: float = 8.0) -> list[Advertisement]:
    """Ascolta gli annunci BLE con bleak (extra smarthome)."""
    from drdeconstruct.acquisition.bluetooth import _require_bleak

    bleak = _require_bleak()

    async def _scan():
        found = await bleak.BleakScanner.discover(timeout=timeout, return_adv=True)
        return [
            Advertisement(
                address=device.address,
                name=adv.local_name or device.name or "",
                rssi=adv.rssi,
                service_data={k.lower(): bytes(v) for k, v in adv.service_data.items()},
                manufacturer_data={k: bytes(v) for k, v in adv.manufacturer_data.items()},
                service_uuids=list(adv.service_uuids),
            )
            for device, adv in found.values()
        ]

    return asyncio.run(_scan())


def scan(timeout: float = 8.0, scanner=scan_advertisements) -> list[SmartDevice]:
    return identify_all(scanner(timeout))
