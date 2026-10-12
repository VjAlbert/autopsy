"""Elenco dei dispositivi USB collegati e accesso ai bus seriali.

Le librerie (pyserial, pyusb) sono extra opzionali: importate in modo pigro
così il resto del programma funziona anche senza. Nessuna scrittura avviene
qui senza passare dai controlli in `safety`.
"""

from __future__ import annotations

from collections.abc import Callable

from drdeconstruct.acquisition.models import DeviceInfo, LinkKind
from drdeconstruct.core.errors import DrDeconstructError

NO_USB_BACKEND_MESSAGE = (
    "La scansione USB non è disponibile: manca la libreria libusb sul computer. "
    "Non è un problema per leggere le schede: premi «Porte seriali», che funziona "
    "senza libusb ed è la via usata dagli adattatori USB-UART (CH340, CP2102, FTDI). "
    "Se ti serve proprio la scansione USB, scarica l'ultima versione di DrDeconstruct, "
    "che include libusb."
)


def _load_usb_backend():
    """Trova un backend libusb per pyusb, o None se non c'è.

    Prima prova la libusb inclusa nel pacchetto `libusb-package` (la DLL viaggia
    con l'app su Windows), poi quella installata nel sistema.
    """
    try:
        import libusb_package

        backend = libusb_package.get_libusb1_backend()
        if backend is not None:
            return backend
    except (ImportError, OSError):
        pass
    try:
        import usb.backend.libusb1

        return usb.backend.libusb1.get_backend()
    except (ImportError, OSError):
        return None


def list_usb_devices(backend_loader: Callable = _load_usb_backend) -> list[DeviceInfo]:
    """Elenca i dispositivi USB tramite pyusb."""
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise DrDeconstructError(
            "Installa l'extra hardware: pip install 'drdeconstruct[hardware]'"
        ) from exc

    backend = backend_loader()
    if backend is None:
        raise DrDeconstructError(NO_USB_BACKEND_MESSAGE)
    try:
        found = list(usb.core.find(find_all=True, backend=backend))
    except usb.core.NoBackendError as exc:
        raise DrDeconstructError(NO_USB_BACKEND_MESSAGE) from exc

    devices = []
    for dev in found:
        try:
            product = usb.util.get_string(dev, dev.iProduct) or "?"
        except (ValueError, NotImplementedError, usb.core.USBError):
            # Su Windows il nome si legge solo se il dispositivo usa il driver WinUSB.
            product = "nome non leggibile"
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
