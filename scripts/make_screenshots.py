"""Generate the README screenshots straight from the GUI, with demo data.

Usage (no display needed):
    QT_QPA_PLATFORM=offscreen python scripts/make_screenshots.py [out_dir]

Nothing calls a model or touches hardware: every page is filled with the same
fake results the test suite uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from drdeconstruct.config import Settings
    from drdeconstruct.doctor import Check
    from drdeconstruct.gui.main_window import MainWindow
    from drdeconstruct.smarthome.inventory import Inventory
    from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice
    from drdeconstruct.web.extract import build_snapshot
    from drdeconstruct.web.schemas import WebAnalysis
    from tests.test_web import PAGE, WEB_PAYLOAD

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    win = MainWindow(Settings(backend="claude-code"))
    win.resize(1280, 1250)
    win.show()

    win.home_page.set_checks(
        [
            Check("claude-code", "Claude Code", True, "Installato. Usa il tuo abbonamento."),
            Check("ghidra", "Ghidra (decompilatore gratuito)", True, "Pronto in C:\\Ghidra."),
            Check(
                "flashrom",
                "flashrom (lettura memorie flash)",
                False,
                "Non installato. Serve solo con un programmatore.",
                optional=True,
            ),
        ]
    )
    win._set_engine_state(True)

    analysis = win.analysis_page
    analysis._load_sample()
    analysis.show_result(
        {
            "function_purpose": "Calcola il CRC-32 (IEEE 802.3) di un buffer di byte.",
            "control_flow": [
                "Parte da 0xFFFFFFFF",
                "Per ogni byte: XOR con il CRC, poi 8 passi di shift e XOR con 0xEDB88320",
                "Restituisce il complemento del risultato",
            ],
            "renames": [
                {
                    "original": "FUN_00401a20",
                    "proposed": "crc32_compute",
                    "kind": "function",
                    "rationale": "polinomio 0xEDB88320 riflesso",
                    "confidence": "high",
                },
                {
                    "original": "param_1",
                    "proposed": "data",
                    "kind": "parameter",
                    "rationale": "puntatore letto byte per byte",
                    "confidence": "high",
                },
                {
                    "original": "param_2",
                    "proposed": "length",
                    "kind": "parameter",
                    "rationale": "contatore decrementato fino a 0",
                    "confidence": "high",
                },
            ],
            "rewritten_code": "uint32_t crc32_compute(const uint8_t *data, int length)\n{\n"
            "    uint32_t crc = 0xFFFFFFFF;\n    /* ... */\n    return ~crc;\n}",
            "algorithm_notes": "CRC-32 bit a bit, senza tabella.",
            "open_questions": ["Chi chiama questa funzione e su quali pacchetti?"],
        }
    )

    web = win.web_page
    web.url_edit.setText("www.esempio.it")
    web.show_web(
        (build_snapshot("https://esempio.it/", PAGE), WebAnalysis.model_validate(WEB_PAYLOAD))
    )

    home = win.smarthome_tab
    home.set_inventory(
        Inventory(
            [
                SmartDevice(
                    Ecosystem.XIAOMI, Channel.MIIO, "miio:1", name="Robot S5", address="10.0.0.5"
                ),
                SmartDevice(
                    Ecosystem.AQARA, Channel.BLE, "aa", name="lumi.sensor_ht", address="AA:BB"
                ),
                SmartDevice(
                    Ecosystem.TAPO, Channel.TAPO_UDP, "t1", name="P110 Presa", address="10.0.0.9"
                ),
            ],
            {},
        )
    )
    home.device_list.setCurrentRow(0)

    win.devices_page.show_log(
        "U-Boot 2016.07 (Mar 10 2021 - 10:12:41)\nDRAM:  64 MiB\n"
        "SF: Detected XM25QH128A, total 16 MiB\nStarting kernel ...\n"
    )

    shots = {
        "home": "01-home.png",
        "analysis": "02-explain.png",
        "decompile": "03-decompile.png",
        "scaffold": "04-scaffold.png",
        "web": "05-web.png",
        "devices": "06-devices.png",
        "smarthome": "07-smart-home.png",
        "quality": "08-quality.png",
    }
    for key, name in shots.items():
        win.show_page(key)
        for _ in range(5):
            app.processEvents()
        win.grab().save(str(out / name))
        print(out / name)
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
