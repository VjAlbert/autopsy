"""Dispositivi Tapo (TP-Link): scoperta in rete locale e protocollo KLAP.

La scoperta usa UDP 20002: il programma invia una richiesta con una chiave
pubblica RSA usa e getta e il dispositivo risponde con modello, MAC e schema di
cifratura. Non servono credenziali e non si invia nessun comando.

Per leggere lo stato servono email e password dell'account TP-Link: il protocollo
KLAP le usa solo per derivare un hash, e questo modulo non le salva da nessuna
parte. Le telecamere Tapo non usano KLAP ma RTSP/ONVIF, con un account
"telecamera" da creare nell'app.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import struct
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass

from drdeconstruct.core.errors import DrDeconstructError
from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice
from drdeconstruct.smarthome.safety import TAPO_READ_ONLY, CommandGuard

DISCOVERY_PORT = 20002


def _crypto():
    try:
        from cryptography.hazmat.primitives import padding, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise DrDeconstructError(
            "Installa l'extra smarthome: pip install 'drdeconstruct[smarthome]'"
        ) from exc
    return padding, serialization, rsa, Cipher, algorithms, modes


# --- Scoperta -------------------------------------------------------------


def build_discovery_query(public_key_pem: str, serial: int | None = None) -> bytes:
    payload = json.dumps({"params": {"rsa_key": public_key_pem}}).encode()
    serial = serial if serial is not None else int.from_bytes(secrets.token_bytes(4), "big")
    header = struct.pack(">BBHHBBII", 2, 0, 1, len(payload), 17, 0, serial, 0x5A6B7C8D)
    query = bytearray(header + payload)
    query[12:16] = zlib.crc32(query).to_bytes(4, "big")
    return bytes(query)


def _ephemeral_public_key() -> str:
    _padding, serialization, rsa, *_ = _crypto()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def parse_discovery_reply(data: bytes, ip: str) -> SmartDevice:
    try:
        result = json.loads(data[16:].decode("utf-8"))["result"]
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        raise DrDeconstructError("Risposta di scoperta Tapo non valida.") from exc
    schema = result.get("mgt_encrypt_schm") or {}
    encrypt = schema.get("encrypt_type", "")
    device_type = result.get("device_type", "")
    needs = []
    if "CAMERA" in device_type.upper():
        needs.append("account telecamera creato nell'app Tapo (RTSP/ONVIF)")
    elif encrypt.upper() == "KLAP":
        needs.append("email e password dell'account TP-Link (protocollo KLAP)")
    else:
        needs.append(f"protocollo {encrypt or 'sconosciuto'}: non ancora supportato qui")
    details = {
        "device_type": device_type,
        "mac": str(result.get("mac", "")).replace("-", ":"),
        "encrypt_type": encrypt,
        "http_port": str(schema.get("http_port", "")),
        "login_version": str(schema.get("lv", "")),
    }
    return SmartDevice(
        ecosystem=Ecosystem.TAPO,
        channel=Channel.TAPO_UDP,
        identifier=str(result.get("device_id", ip)),
        model=str(result.get("device_model", "")),
        address=str(result.get("ip", ip)),
        needs=needs,
        details={k: v for k, v in details.items() if v},
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
    public_key_pem: str | None = None,
) -> list[SmartDevice]:
    query = build_discovery_query(public_key_pem or _ephemeral_public_key())
    found: dict[str, SmartDevice] = {}
    with socket_factory() as sock:
        sock.settimeout(timeout)
        sock.sendto(query, (target, DISCOVERY_PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (ip, _port) = sock.recvfrom(4096)
            except TimeoutError:
                break
            try:
                found[ip] = parse_discovery_reply(data, ip)
            except DrDeconstructError:
                continue
    return list(found.values())


# --- KLAP ------------------------------------------------------------------


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def auth_hash(username: str, password: str, version: int = 2) -> bytes:
    if version == 1:
        md5 = hashlib.md5  # noqa: S324 - imposto dal protocollo KLAP v1
        return md5(md5(username.encode()).digest() + md5(password.encode()).digest()).digest()
    sha1 = hashlib.sha1  # noqa: S324 - imposto dal protocollo KLAP v2
    return _sha256(sha1(username.encode()).digest() + sha1(password.encode()).digest())


class KlapSession:
    """Cifratura di una sessione KLAP già autenticata."""

    def __init__(self, local_seed: bytes, remote_seed: bytes, user_hash: bytes):
        material = local_seed + remote_seed + user_hash
        self.key = _sha256(b"lsk" + material)[:16]
        full_iv = _sha256(b"iv" + material)
        self.iv = full_iv[:12]
        self.seq = int.from_bytes(full_iv[-4:], "big", signed=True)
        self.sig = _sha256(b"ldk" + material)[:28]

    def _cipher(self, seq: int):
        _p, _s, _r, Cipher, algorithms, modes = _crypto()
        iv = self.iv + seq.to_bytes(4, "big", signed=True)
        return Cipher(algorithms.AES(self.key), modes.CBC(iv))

    def encrypt(self, message: bytes) -> tuple[bytes, int]:
        padding, *_ = _crypto()
        self.seq += 1
        padder = padding.PKCS7(128).padder()
        enc = self._cipher(self.seq).encryptor()
        ciphertext = enc.update(padder.update(message) + padder.finalize()) + enc.finalize()
        signature = _sha256(self.sig + self.seq.to_bytes(4, "big", signed=True) + ciphertext)
        return signature + ciphertext, self.seq

    def decrypt(self, message: bytes, seq: int | None = None) -> bytes:
        padding, *_ = _crypto()
        dec = self._cipher(self.seq if seq is None else seq).decryptor()
        data = dec.update(message[32:]) + dec.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(data) + unpadder.finalize()


@dataclass
class HttpResponse:
    status: int
    body: bytes
    cookie: str = ""


Poster = Callable[[str, bytes, dict[str, str]], HttpResponse]


def _urllib_post(url: str, data: bytes, headers: dict[str, str]) -> HttpResponse:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - URL locale
            cookie = (resp.headers.get("Set-Cookie") or "").split(";")[0]
            return HttpResponse(resp.status, resp.read(), cookie)
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, exc.read())
    except OSError as exc:
        raise DrDeconstructError(f"Impossibile contattare {url}: {exc}") from exc


class TapoClient:
    """Client KLAP per prese, lampadine e hub Tapo."""

    def __init__(
        self,
        ip: str,
        username: str,
        password: str,
        port: int = 80,
        poster: Poster = _urllib_post,
    ):
        self.base = f"http://{ip}:{port}/app"
        self._username = username
        self._password = password
        self._post = poster
        self._session: KlapSession | None = None
        self._cookie = ""

    def _handshake(self) -> None:
        local_seed = secrets.token_bytes(16)
        r1 = self._post(f"{self.base}/handshake1", local_seed, {})
        if r1.status != 200 or len(r1.body) < 48:
            raise DrDeconstructError(f"Handshake KLAP rifiutato (HTTP {r1.status}).")
        remote_seed, server_hash = r1.body[:16], r1.body[16:48]
        self._cookie = r1.cookie
        for version in (2, 1):
            user_hash = auth_hash(self._username, self._password, version)
            if _sha256(local_seed + remote_seed + user_hash) == server_hash:
                break
        else:
            raise DrDeconstructError(
                "Credenziali TP-Link rifiutate dal dispositivo (email o password errate)."
            )
        r2 = self._post(
            f"{self.base}/handshake2",
            _sha256(remote_seed + local_seed + user_hash),
            self._headers(),
        )
        if r2.status != 200:
            raise DrDeconstructError(f"Secondo handshake KLAP rifiutato (HTTP {r2.status}).")
        self._session = KlapSession(local_seed, remote_seed, user_hash)

    def _headers(self) -> dict[str, str]:
        return {"Cookie": self._cookie} if self._cookie else {}

    def request(self, method: str, params: dict | None = None, guard: CommandGuard | None = None):
        (guard or CommandGuard()).check(method, TAPO_READ_ONLY)
        if self._session is None:
            self._handshake()
        assert self._session is not None
        body = {"method": method, "request_time_milis": int(time.time() * 1000)}
        if params:
            body["params"] = params
        payload, seq = self._session.encrypt(json.dumps(body).encode())
        resp = self._post(f"{self.base}/request?seq={seq}", payload, self._headers())
        if resp.status != 200:
            self._session = None
            raise DrDeconstructError(f"Richiesta KLAP fallita (HTTP {resp.status}).")
        reply = json.loads(self._session.decrypt(resp.body, seq))
        if reply.get("error_code", 0) != 0:
            raise DrDeconstructError(
                f"Il dispositivo ha risposto con errore {reply['error_code']}."
            )
        return reply.get("result", {})

    def device_info(self) -> dict:
        return self.request("get_device_info")
