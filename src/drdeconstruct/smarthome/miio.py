"""Protocollo miIO dei dispositivi Xiaomi su WiFi (robot, purificatori, lampade, prese).

La scoperta ("hello") non richiede il token e non invia comandi: il dispositivo
risponde con il suo ID e un timestamp. I comandi veri sono cifrati con AES-128-CBC,
con chiave e IV derivati dal token di 32 caratteri esadecimali del dispositivo.

Sui firmware recenti il token non compare più nella risposta hello (è tutto 0xFF
o 0x00): va estratto dal cloud Xiaomi con il proprio account o dal dispositivo
dopo il rooting.
"""

from __future__ import annotations

import hashlib
import json
import socket
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

from drdeconstruct.core.errors import DrDeconstructError
from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice
from drdeconstruct.smarthome.safety import MIIO_READ_ONLY, CommandGuard

PORT = 54321
MAGIC = 0x2131
HELLO = bytes.fromhex("21310020") + b"\xff" * 28


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()  # noqa: S324 - imposto dal protocollo


def _cipher(token: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise DrDeconstructError(
            "Installa l'extra smarthome: pip install 'drdeconstruct[smarthome]'"
        ) from exc
    key = _md5(token)
    iv = _md5(key + token)
    return Cipher(algorithms.AES(key), modes.CBC(iv))


def encrypt(token: bytes, plaintext: bytes) -> bytes:
    from cryptography.hazmat.primitives import padding

    padder = padding.PKCS7(128).padder()
    data = padder.update(plaintext) + padder.finalize()
    enc = _cipher(token).encryptor()
    return enc.update(data) + enc.finalize()


def decrypt(token: bytes, ciphertext: bytes) -> bytes:
    from cryptography.hazmat.primitives import padding

    dec = _cipher(token).decryptor()
    data = dec.update(ciphertext) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(data) + unpadder.finalize()


@dataclass(frozen=True)
class Header:
    device_id: int
    stamp: int
    checksum: bytes
    length: int

    @property
    def token_exposed(self) -> bool:
        return self.checksum not in (b"\xff" * 16, b"\x00" * 16)


def parse_header(packet: bytes) -> Header:
    if len(packet) < 32:
        raise DrDeconstructError("Pacchetto miIO troppo corto.")
    magic, length, _unknown, device_id, stamp = struct.unpack_from(">HHIII", packet, 0)
    if magic != MAGIC:
        raise DrDeconstructError("Il pacchetto non è miIO (magic errato).")
    return Header(device_id=device_id, stamp=stamp, checksum=packet[16:32], length=length)


def build_packet(token: bytes, device_id: int, stamp: int, payload: dict) -> bytes:
    body = encrypt(token, json.dumps(payload, separators=(",", ":")).encode())
    head = struct.pack(">HHIII", MAGIC, 32 + len(body), 0, device_id, stamp)
    checksum = _md5(head + token + body)
    return head + checksum + body


def parse_reply(token: bytes, packet: bytes) -> dict:
    header = parse_header(packet)
    body = packet[32 : header.length]
    if _md5(packet[:16] + token + body) != header.checksum:
        raise DrDeconstructError("Checksum miIO errato: il token è sbagliato?")
    if not body:
        return {}
    return json.loads(decrypt(token, body).rstrip(b"\x00").decode("utf-8", errors="replace"))


def hello_to_device(reply: bytes, ip: str) -> SmartDevice:
    header = parse_header(reply)
    needs = []
    details = {"device_id": str(header.device_id), "stamp": str(header.stamp)}
    if header.token_exposed:
        details["token_exposed"] = "true"
    else:
        details["token_exposed"] = "false"
        needs.append("token miIO (dal cloud Xiaomi con il tuo account, o dopo il rooting)")
    return SmartDevice(
        ecosystem=Ecosystem.XIAOMI,
        channel=Channel.MIIO,
        identifier=f"miio:{header.device_id}",
        address=ip,
        needs=needs,
        details=details,
    )


SocketFactory = Callable[[], socket.socket]


def _udp_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return sock


def discover(
    timeout: float = 3.0,
    target: str = "255.255.255.255",
    socket_factory: SocketFactory = _udp_socket,
) -> list[SmartDevice]:
    """Invia un hello in broadcast e raccoglie le risposte, senza comandi."""
    found: dict[str, SmartDevice] = {}
    with socket_factory() as sock:
        sock.settimeout(timeout)
        sock.sendto(HELLO, (target, PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (ip, _port) = sock.recvfrom(1024)
            except TimeoutError:
                break
            try:
                found[ip] = hello_to_device(data, ip)
            except DrDeconstructError:
                continue
    return list(found.values())


class MiioClient:
    """Client miIO per un singolo dispositivo di cui l'operatore conosce il token."""

    def __init__(
        self,
        ip: str,
        token_hex: str,
        timeout: float = 5.0,
        socket_factory: SocketFactory = _udp_socket,
    ):
        try:
            self.token = bytes.fromhex(token_hex.strip())
        except ValueError as exc:
            raise DrDeconstructError("Il token miIO deve essere esadecimale.") from exc
        if len(self.token) != 16:
            raise DrDeconstructError("Il token miIO deve avere 32 caratteri esadecimali.")
        self.ip = ip
        self.timeout = timeout
        self._socket_factory = socket_factory
        self._id = 0

    def send(self, method: str, params=None, guard: CommandGuard | None = None) -> dict:
        (guard or CommandGuard()).check(method, MIIO_READ_ONLY)
        with self._socket_factory() as sock:
            sock.settimeout(self.timeout)
            sock.sendto(HELLO, (self.ip, PORT))
            try:
                hello, _ = sock.recvfrom(1024)
            except TimeoutError as exc:
                raise DrDeconstructError(f"{self.ip} non risponde su UDP {PORT}.") from exc
            header = parse_header(hello)
            self._id += 1
            payload = {"id": self._id, "method": method, "params": params or []}
            sock.sendto(
                build_packet(self.token, header.device_id, header.stamp + 1, payload),
                (
                    self.ip,
                    PORT,
                ),
            )
            try:
                reply, _ = sock.recvfrom(4096)
            except TimeoutError as exc:
                raise DrDeconstructError(
                    "Nessuna risposta al comando: token errato o metodo non supportato."
                ) from exc
        return parse_reply(self.token, reply)

    def info(self) -> dict:
        return self.send("miIO.info")
