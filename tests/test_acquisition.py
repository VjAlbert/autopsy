import subprocess
from pathlib import Path

import pytest

from drdeconstruct.acquisition.flash import FlashTool
from drdeconstruct.acquisition.safety import WriteGuard, sha256, verify_readback
from drdeconstruct.core.errors import DrDeconstructError, SafetyError


def test_write_guard_requires_backup_and_confirmation():
    with pytest.raises(SafetyError, match="backup"):
        WriteGuard(confirmed=True, backup_done=False).check(b"abc")
    with pytest.raises(SafetyError, match="conferma"):
        WriteGuard(confirmed=False, backup_done=True).check(b"abc")


def test_write_guard_checks_size():
    with pytest.raises(SafetyError, match="dimensione"):
        WriteGuard(confirmed=True, backup_done=True, expected_size=4).check(b"abcde")
    WriteGuard(confirmed=True, backup_done=True, expected_size=3).check(b"abc")


def test_verify_readback_detects_mismatch():
    verify_readback(b"same", b"same")
    with pytest.raises(SafetyError, match="Verifica fallita"):
        verify_readback(b"written", b"other")


def _fake_runner(sink):
    def runner(cmd, **kwargs):
        sink.append(cmd)
        if "-r" in cmd:
            Path(cmd[cmd.index("-r") + 1]).write_bytes(b"\xde\xad\xbe\xef")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    return runner


def test_backup_reads_and_hashes(tmp_path):
    cmds: list = []
    tool = FlashTool("ch341a_spi", runner=_fake_runner(cmds))
    img = tool.backup(tmp_path / "orig.bin")
    assert img.size == 4
    assert img.sha256 == sha256(b"\xde\xad\xbe\xef")
    assert cmds[0][:3] == ["flashrom", "-p", "ch341a_spi"]


def test_update_blocked_without_backup(tmp_path):
    tool = FlashTool("ch341a_spi", runner=_fake_runner([]))
    new = tmp_path / "new.bin"
    new.write_bytes(b"\xde\xad\xbe\xef")
    with pytest.raises(SafetyError):
        tool.update(new, WriteGuard(confirmed=True, backup_done=False), tmp_path / "rb.bin")


def test_update_requires_readback(tmp_path):
    tool = FlashTool("ch341a_spi", runner=_fake_runner([]))
    new = tmp_path / "new.bin"
    new.write_bytes(b"\xde\xad\xbe\xef")
    with pytest.raises(SafetyError, match="rilettura"):
        tool.update(new, WriteGuard(confirmed=True, backup_done=True), readback_path=None)


def test_update_succeeds_with_matching_readback(tmp_path):
    cmds: list = []
    tool = FlashTool("ch341a_spi", runner=_fake_runner(cmds))
    new = tmp_path / "new.bin"
    new.write_bytes(b"\xde\xad\xbe\xef")
    tool.update(new, WriteGuard(confirmed=True, backup_done=True), tmp_path / "rb.bin")
    assert any("-w" in c for c in cmds) and any("-r" in c for c in cmds)


def test_flashrom_missing(tmp_path):
    def runner(cmd, **kwargs):
        raise FileNotFoundError

    with pytest.raises(DrDeconstructError, match="flashrom"):
        FlashTool("ch341a_spi", runner=runner).backup(tmp_path / "x.bin")


def _fake_pyusb(monkeypatch, devices=(), raise_no_backend=False):
    """Installa un finto pyusb in sys.modules: la CI non ha né pyusb né libusb."""
    import sys
    import types

    core = types.ModuleType("usb.core")

    class USBError(Exception):
        pass

    class NoBackendError(ValueError):
        pass

    def find(find_all=False, backend=None):
        if raise_no_backend:
            raise NoBackendError("No backend available")
        return iter(devices)

    core.USBError, core.NoBackendError, core.find = USBError, NoBackendError, find
    util = types.ModuleType("usb.util")

    def get_string(dev, index):
        raise USBError("access denied")

    util.get_string = get_string
    pkg = types.ModuleType("usb")
    pkg.core, pkg.util = core, util
    monkeypatch.setitem(sys.modules, "usb", pkg)
    monkeypatch.setitem(sys.modules, "usb.core", core)
    monkeypatch.setitem(sys.modules, "usb.util", util)


def test_usb_scan_without_backend_explains_and_points_to_serial(monkeypatch):
    from drdeconstruct.acquisition.usb import list_usb_devices

    _fake_pyusb(monkeypatch)
    with pytest.raises(DrDeconstructError) as err:
        list_usb_devices(backend_loader=lambda: None)
    assert "libusb" in str(err.value)
    assert "Porte seriali" in str(err.value)


def test_usb_scan_no_backend_error_is_translated(monkeypatch):
    from drdeconstruct.acquisition.usb import list_usb_devices

    _fake_pyusb(monkeypatch, raise_no_backend=True)
    with pytest.raises(DrDeconstructError, match="Porte seriali"):
        list_usb_devices(backend_loader=lambda: object())


def test_usb_scan_lists_devices_even_without_readable_names(monkeypatch):
    from types import SimpleNamespace

    from drdeconstruct.acquisition.usb import list_usb_devices

    dev = SimpleNamespace(idVendor=0x1A86, idProduct=0x7523, iProduct=2, bus=1, address=4)
    _fake_pyusb(monkeypatch, devices=[dev])
    devices = list_usb_devices(backend_loader=lambda: object())
    assert devices[0].identifier == "1a86:7523"
    assert devices[0].label == "nome non leggibile"
