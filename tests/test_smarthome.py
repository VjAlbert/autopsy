import json
import struct
import zlib

import pytest

from drdeconstruct import cli
from drdeconstruct.core.errors import DrDeconstructError, SafetyError
from drdeconstruct.smarthome import ble, mdns, miio, tapo, valetudo
from drdeconstruct.smarthome.guide import SmartHomeAdvisor
from drdeconstruct.smarthome.inventory import Inventory, build_inventory, merge
from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice
from drdeconstruct.smarthome.prompts import redact
from tests.conftest import FakeLLM

TOKEN_HEX = "00112233445566778899aabbccddeeff"
TOKEN = bytes.fromhex(TOKEN_HEX)


# --- Bluetooth LE / MiBeacon -------------------------------------------------


def _mibeacon(frame_ctrl: int, product: int, mac: bytes = b"", objects: bytes = b"") -> bytes:
    return struct.pack("<HHB", frame_ctrl, product, 7) + mac[::-1] + objects


def test_parse_mibeacon_plain_temperature_humidity():
    obj = struct.pack("<HBhH", 0x100D, 4, 215, 563)
    data = _mibeacon(0x5050, 0x055B, bytes.fromhex("A4C138112233"), obj)
    beacon = ble.parse_mibeacon(data)
    assert beacon.mac == "A4:C1:38:11:22:33"
    assert not beacon.encrypted
    assert beacon.version == 5
    assert beacon.readings == {"temperature_c": 21.5, "humidity_pct": 56.3}
    assert "LYWSD03MMC" in beacon.product


def test_identify_encrypted_beacon_asks_for_bindkey():
    data = _mibeacon(0x5858, 0x0863, bytes.fromhex("54EF44AABBCC")) + b"\x01\x02\x03"
    adv = ble.Advertisement("54:EF:44:AA:BB:CC", "lumi.motion", -60, {ble.MIBEACON_UUID: data})
    dev = ble.identify(adv)
    assert dev.ecosystem is Ecosystem.AQARA
    assert dev.channel is Channel.BLE
    assert any("bindkey" in n for n in dev.needs)
    assert dev.details["encrypted"] == "True"


def test_identify_by_name_and_ignore_others():
    tapo_adv = ble.Advertisement("11:22:33:44:55:66", "Tapo_Plug_1234")
    robot_adv = ble.Advertisement("aa", "roborock-vacuum-s5")
    other = ble.Advertisement("bb", "JBL Flip 5")
    devices = ble.identify_all([tapo_adv, robot_adv, other])
    assert [d.ecosystem for d in devices] == [Ecosystem.TAPO, Ecosystem.XIAOMI]
    assert "WiFi" in devices[1].needs[0]


def test_identify_short_payload_is_ignored():
    adv = ble.Advertisement("x", "", None, {ble.MIBEACON_UUID: b"\x01"})
    assert ble.identify(adv) is None


def test_ble_scan_uses_injected_scanner():
    adv = ble.Advertisement("aa", "", None, {}, {ble.XIAOMI_COMPANY_ID: b"\x00"})
    devices = ble.scan(timeout=1, scanner=lambda t: [adv])
    assert devices[0].ecosystem is Ecosystem.XIAOMI


# --- miIO ----------------------------------------------------------------------


def _hello_reply(device_id=0x0ABCDEF0, stamp=1000, checksum=b"\xff" * 16) -> bytes:
    return struct.pack(">HHIII", 0x2131, 32, 0, device_id, stamp) + checksum


class FakeMiioDevice:
    """Socket finto che risponde come un dispositivo miIO."""

    def __init__(self, token=TOKEN, answer=None, silent=False):
        self.token = token
        self.answer = answer or {"model": "roborock.vacuum.s5", "fw_ver": "3.5.8"}
        self.silent = silent
        self.inbox: list[bytes] = []
        self.received: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def settimeout(self, t):
        pass

    def sendto(self, data, addr):
        if data == miio.HELLO:
            self.inbox.append(_hello_reply())
            return
        request = miio.parse_reply(self.token, data)
        self.received.append(request)
        if not self.silent:
            reply = {"id": request["id"], "result": self.answer}
            self.inbox.append(miio.build_packet(self.token, 0x0ABCDEF0, 1001, reply))

    def recvfrom(self, size):
        if not self.inbox:
            raise TimeoutError
        return self.inbox.pop(0), ("192.168.1.50", miio.PORT)


def test_miio_encrypt_roundtrip():
    assert miio.decrypt(TOKEN, miio.encrypt(TOKEN, b'{"a":1}')) == b'{"a":1}'


def test_miio_packet_roundtrip_and_wrong_token():
    packet = miio.build_packet(TOKEN, 42, 7, {"id": 1, "method": "miIO.info", "params": []})
    assert miio.parse_reply(TOKEN, packet)["method"] == "miIO.info"
    with pytest.raises(DrDeconstructError, match="token"):
        miio.parse_reply(b"\x01" * 16, packet)


def test_hello_reply_token_exposure():
    hidden = miio.hello_to_device(_hello_reply(), "10.0.0.2")
    assert hidden.details["token_exposed"] == "false"
    assert any("token" in n for n in hidden.needs)
    exposed = miio.hello_to_device(_hello_reply(checksum=TOKEN), "10.0.0.2")
    assert exposed.details["token_exposed"] == "true"
    assert exposed.needs == []


def test_miio_discover_with_fake_socket():
    found = miio.discover(timeout=0.5, socket_factory=lambda: FakeMiioDevice())
    assert len(found) == 1
    assert found[0].address == "192.168.1.50"
    assert found[0].details["device_id"] == str(0x0ABCDEF0)


def test_miio_client_reads_info():
    device = FakeMiioDevice()
    client = miio.MiioClient("192.168.1.50", TOKEN_HEX, socket_factory=lambda: device)
    reply = client.info()
    assert reply["result"]["model"] == "roborock.vacuum.s5"
    assert device.received[0]["method"] == "miIO.info"


def test_miio_client_blocks_write_without_confirm():
    device = FakeMiioDevice()
    client = miio.MiioClient("192.168.1.50", TOKEN_HEX, socket_factory=lambda: device)
    with pytest.raises(SafetyError, match="app_start"):
        client.send("app_start")
    assert device.received == []
    from drdeconstruct.smarthome.safety import CommandGuard

    client.send("app_start", guard=CommandGuard(confirmed=True))
    assert device.received[0]["method"] == "app_start"


def test_miio_client_validates_token_and_timeout():
    with pytest.raises(DrDeconstructError, match="32"):
        miio.MiioClient("1.2.3.4", "abcd")
    with pytest.raises(DrDeconstructError, match="esadecimale"):
        miio.MiioClient("1.2.3.4", "zz" * 16)
    silent = FakeMiioDevice(silent=True)
    client = miio.MiioClient("1.2.3.4", TOKEN_HEX, socket_factory=lambda: silent)
    with pytest.raises(DrDeconstructError, match="Nessuna risposta"):
        client.info()


# --- Tapo ----------------------------------------------------------------------


def _tapo_reply(device_type="SMART.TAPOPLUG", model="P110(EU)", encrypt="KLAP") -> bytes:
    body = {
        "error_code": 0,
        "result": {
            "device_id": "abc123",
            "device_type": device_type,
            "device_model": model,
            "ip": "192.168.1.60",
            "mac": "AA-BB-CC-DD-EE-FF",
            "mgt_encrypt_schm": {"encrypt_type": encrypt, "http_port": 80, "lv": 2},
        },
    }
    return b"\x02" + b"\x00" * 15 + json.dumps(body).encode()


def test_tapo_discovery_query_has_valid_crc():
    query = tapo.build_discovery_query("PEM", serial=1)
    version, _t, op, size, flags = struct.unpack_from(">BBHHB", query)
    assert (version, op, flags) == (2, 1, 17)
    assert size == len(query) - 16
    check = bytearray(query)
    check[12:16] = (0x5A6B7C8D).to_bytes(4, "big")
    assert zlib.crc32(check).to_bytes(4, "big") == query[12:16]


def test_tapo_parse_plug_and_camera():
    plug = tapo.parse_discovery_reply(_tapo_reply(), "192.168.1.60")
    assert plug.model == "P110(EU)"
    assert plug.details["mac"] == "AA:BB:CC:DD:EE:FF"
    assert "KLAP" in plug.needs[0]
    cam = tapo.parse_discovery_reply(_tapo_reply("SMART.IPCAMERA", "C200", "AES"), "x")
    assert "RTSP" in cam.needs[0]
    with pytest.raises(DrDeconstructError):
        tapo.parse_discovery_reply(b"\x00" * 16 + b"not json", "x")


class FakeUdp:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def settimeout(self, t):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recvfrom(self, size):
        if not self.replies:
            raise TimeoutError
        return self.replies.pop(0)


def test_tapo_discover_with_fake_socket():
    sock = FakeUdp([(_tapo_reply(), ("192.168.1.60", 20002)), (b"junk", ("192.168.1.61", 1))])
    found = tapo.discover(timeout=0.5, socket_factory=lambda: sock, public_key_pem="PEM")
    assert [d.address for d in found] == ["192.168.1.60"]
    assert sock.sent[0][1] == ("255.255.255.255", tapo.DISCOVERY_PORT)


class FakeKlapDevice:
    """Simula il lato dispositivo del protocollo KLAP v2."""

    def __init__(self, username, password):
        self.user_hash = tapo.auth_hash(username, password)
        self.remote_seed = b"R" * 16
        self.session = None
        self.methods = []

    def __call__(self, url, data, headers):
        if url.endswith("/handshake1"):
            self.local_seed = data
            server_hash = tapo._sha256(data + self.remote_seed + self.user_hash)
            return tapo.HttpResponse(200, self.remote_seed + server_hash, "TP_SESSIONID=xyz")
        assert headers.get("Cookie") == "TP_SESSIONID=xyz"
        if url.endswith("/handshake2"):
            expected = tapo._sha256(self.remote_seed + self.local_seed + self.user_hash)
            if data != expected:
                return tapo.HttpResponse(403, b"")
            self.session = tapo.KlapSession(self.local_seed, self.remote_seed, self.user_hash)
            return tapo.HttpResponse(200, b"")
        seq = int(url.split("seq=")[1])
        request = json.loads(self.session.decrypt(data, seq))
        self.methods.append(request["method"])
        reply = json.dumps({"error_code": 0, "result": {"model": "P110", "device_on": True}})
        self.session.seq = seq - 1
        encrypted, _ = self.session.encrypt(reply.encode())
        return tapo.HttpResponse(200, encrypted)


def test_tapo_klap_reads_device_info():
    device = FakeKlapDevice("me@example.com", "secret")
    client = tapo.TapoClient("192.168.1.60", "me@example.com", "secret", poster=device)
    assert client.device_info()["model"] == "P110"
    assert client.request("get_current_power")["device_on"] is True
    assert device.methods == ["get_device_info", "get_current_power"]


def test_tapo_wrong_password_and_write_guard():
    device = FakeKlapDevice("me@example.com", "secret")
    bad = tapo.TapoClient("ip", "me@example.com", "wrong", poster=device)
    with pytest.raises(DrDeconstructError, match="Credenziali"):
        bad.device_info()
    good = tapo.TapoClient("ip", "me@example.com", "secret", poster=device)
    with pytest.raises(SafetyError, match="set_device_info"):
        good.request("set_device_info", {"device_on": False})
    assert device.methods == []


# --- mDNS, Valetudo ------------------------------------------------------------


def test_mdns_classification():
    records = [
        mdns.MdnsRecord(
            "_miio._udp.local.", "zhimi-airpurifier-v6_miio123._miio._udp.local.", ["10.0.0.5"]
        ),
        mdns.MdnsRecord(
            "_hap._tcp.local.",
            "Aqara Hub-M2._hap._tcp.local.",
            ["10.0.0.6"],
            8080,
            {"md": "Aqara Hub-M2"},
        ),
        mdns.MdnsRecord(
            "_valetudo._tcp.local.", "valetudo-robot._valetudo._tcp.local.", ["10.0.0.7"]
        ),
        mdns.MdnsRecord("_hap._tcp.local.", "Eve Energy._hap._tcp.local."),
    ]
    devices = mdns.discover(browser=lambda t: records)
    assert [d.ecosystem for d in devices] == [
        Ecosystem.XIAOMI,
        Ecosystem.AQARA,
        Ecosystem.VALETUDO,
        Ecosystem.UNKNOWN,
    ]
    assert devices[0].name == "zhimi-airpurifier-v6_miio123"
    assert devices[1].model == "Aqara Hub-M2"
    assert "HomeKit" in devices[1].needs[0]
    assert "api/v2" in devices[2].needs[0]


def test_valetudo_read_robot():
    pages = {
        "/robot": {"manufacturer": "Roborock", "modelName": "S5"},
        "/valetudo/version": {"release": "2024.06.0"},
        "/robot/state/attributes": [{"__class": "BatteryStateAttribute", "level": 80}],
    }

    def getter(url):
        return json.dumps(pages[url.split("/api/v2")[1]]).encode()

    data = valetudo.read_robot("10.0.0.7", getter=getter)
    assert data["robot"]["modelName"] == "S5"
    assert data["state"][0]["level"] == 80


# --- Inventario e guida --------------------------------------------------------


def _dev(channel, address="", mac="", ecosystem=Ecosystem.XIAOMI, needs=None, **details):
    if mac:
        details["mac"] = mac
    return SmartDevice(
        ecosystem,
        channel,
        f"id-{channel.value}",
        address=address,
        needs=needs or [],
        details=details,
    )


def test_merge_same_device_across_channels():
    a = _dev(Channel.MIIO, "10.0.0.5", needs=["token"])
    b = _dev(Channel.MDNS, "10.0.0.5", needs=["token", "altro"])
    c = _dev(Channel.TAPO_UDP, "10.0.0.9", ecosystem=Ecosystem.TAPO)
    merged = merge([a, b, c])
    assert len(merged) == 2
    assert merged[0].details["channels"] == "miio,mdns"
    assert merged[0].needs == ["token", "altro"]


def test_build_inventory_keeps_going_on_errors():
    def broken():
        raise DrDeconstructError("Bluetooth non disponibile")

    inv = build_inventory({"ble": broken, "miio": lambda: [_dev(Channel.MIIO, "10.0.0.5")]})
    assert len(inv.devices) == 1
    assert inv.errors == {"ble": "Bluetooth non disponibile"}


GUIDE_PAYLOAD = {
    "summary": "Un robot Xiaomi raggiungibile via miIO.",
    "devices": [
        {
            "device": "roborock.vacuum.s5",
            "ecosystem": "xiaomi",
            "reachable_now": False,
            "connection_path": "miIO su WiFi",
            "requirements": ["token"],
            "firmware_path": "rooting via Dustbuilder, poi Valetudo",
            "risks": ["garanzia"],
            "confidence": "medium",
        }
    ],
    "not_reachable": ["sensori Zigbee senza hub"],
    "next_steps": ["estrai il token dal cloud"],
}


def test_redact_removes_secrets():
    inv = {
        "devices": [
            {"details": {"token": "abc", "bindkey": "x", "token_exposed": "true", "mac": "AA"}}
        ]
    }
    assert redact(inv)["devices"][0]["details"] == {"token_exposed": "true", "mac": "AA"}


def test_advisor_sends_redacted_inventory():
    llm = FakeLLM(GUIDE_PAYLOAD)
    inv = Inventory([_dev(Channel.MIIO, "10.0.0.5", token="deadbeef")])
    guide = SmartHomeAdvisor(llm).advise(inv, "robot in salotto")
    assert guide.devices[0].firmware_path.startswith("rooting")
    system, user, _schema = llm.calls[0]
    assert "deadbeef" not in user
    assert "robot in salotto" in user
    assert "Zigbee" in system


# --- CLI -----------------------------------------------------------------------


def test_cli_home_scan(monkeypatch, tmp_path):
    from drdeconstruct.smarthome import inventory

    monkeypatch.setattr(
        inventory,
        "default_scanners",
        lambda timeout, ble=True, lan=True: {"miio": lambda: [_dev(Channel.MIIO, "10.0.0.5")]},
    )
    out = tmp_path / "inv.json"
    assert cli.main(["home", "scan", "-o", str(out)]) == 0
    assert json.loads(out.read_text())["devices"][0]["address"] == "10.0.0.5"


def test_cli_home_guide_from_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "make_backend", lambda settings: FakeLLM(GUIDE_PAYLOAD))
    inv = tmp_path / "inv.json"
    inv.write_text(Inventory([_dev(Channel.MIIO, "10.0.0.5")]).to_json())
    out = tmp_path / "guide.json"
    assert cli.main(["home", "guide", "--inventory", str(inv), "-o", str(out)]) == 0
    assert "Dustbuilder" in out.read_text()


def test_cli_home_miio_blocks_write(monkeypatch, capsys):
    monkeypatch.setenv("DRDEC_MIIO_TOKEN", TOKEN_HEX)
    assert cli.main(["home", "miio", "10.0.0.5", "--method", "app_start"]) == 1
    assert "--confirm" in capsys.readouterr().err


def test_cli_home_valetudo(monkeypatch, capsys):
    monkeypatch.setattr(valetudo, "read_robot", lambda ip: {"robot": {"modelName": "S5"}})
    assert cli.main(["home", "valetudo", "10.0.0.7"]) == 0
    assert "S5" in capsys.readouterr().out
