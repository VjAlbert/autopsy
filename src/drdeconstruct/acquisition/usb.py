"""Elenco dei dispositivi USB collegati e accesso ai bus seriali.

Le librerie (pyserial, pyusb) sono extra opzionali: importate in modo pigro
così il resto del programma funziona anche senza. Nessuna scrittura avviene
qui senza passare dai controlli in `safety`.
"""

from __future__ import annotations

from collections.abc import Callable

from drdeconstruct.acquisition.models import DeviceInfo, LinkKind
from drdeconstruct.core.errors import DrDeconstructError


def list_usb_devices() -> list[DeviceInfo]:
    """Elenca i dispositivi USB tramite pyusb."""
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise DrDeconstructError(
            "Installa l'extra hardware: pip install 'drdeconstruct[hardware]'"
        ) from exc

    devices = []
    for dev in usb.core.find(find_all=True):
        try:
            product = usb.util.get_string(dev, dev.iProduct) or "?"
        except (ValueError, usb.core.USBError):
            product = "?"
        devices.append(
            DeviceInfo(
                kind=LinkKind.USB,
                identifier=f"{dev.idVendor:04x}:{dev.idProduct:04x}",
                label=product,
                details={"bus": str(dev.bus), "address": str(dev.address)},
            )
        )
    return devices


def list_serial_ports() -> list[DeviceInfo]:
    """Elenca le porte seriali (adattatori USB-UART come CH340, CP2102)."""
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise DrDeconstructError(
            "Installa l'extra hardware: pip install 'drdeconstruct[hardware]'"
        ) from exc

    ports = []
    for port in list_ports.comports():
        ports.append(
            DeviceInfo(
                kind=LinkKind.SERIAL,
                identifier=port.device,
                label=port.description or port.device,
                details={"hwid": port.hwid or ""},
            )
        )
    return ports


class SerialConsole:
    """Legge il log di avvio o la console di un dispositivo via seriale."""

    def __init__(self, port: str, baudrate: int = 115200, opener: Callable | None = None):
        self.port = port
        self.baudrate = baudrate
        self._opener = opener

    def _open(self):
        if self._opener is not None:
            return self._opener(self.port, self.baudrate)
        try:
            import serial
        except ImportError as exc:
            raise DrDeconstructError(
                "Installa l'extra hardware: pip install 'drdeconstruct[hardware]'"
            ) from exc
        return serial.Serial(self.port, self.baudrate, timeout=1)

    def capture(self, seconds: float = 10.0) -> str:
        """Raccoglie il testo che arriva dalla seriale per N secondi."""
        import time

        conn = self._open()
        chunks: list[bytes] = []
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                data = conn.read(4096)
                if data:
                    chunks.append(data)
        finally:
            conn.close()
        return b"".join(chunks).decode("utf-8", errors="replace")
