"""Scheda «Casa smart»: dispositivi Xiaomi, Aqara e Tapo, guidata passo passo.

Pensata per chi non conosce i protocolli: ogni passo ha un pulsante, i testi
spiegano cosa fare, token e password si chiedono solo quando servono e non
vengono salvati. I comandi che modificano un dispositivo stanno in una sezione
«Avanzate» e chiedono sempre una conferma.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QTextEdit,
)

from drdeconstruct.config import Settings
from drdeconstruct.gui.components import Page, button, row
from drdeconstruct.smarthome.inventory import Inventory
from drdeconstruct.smarthome.models import SmartDevice
from drdeconstruct.smarthome.presenter import (
    SMART_HOME_STEPS,
    Action,
    action_for,
    describe_device,
    describe_errors,
    format_guide,
    format_state,
)

Runner = Callable[..., None]


class SmartHomeTab(Page):
    nav_title = "Casa smart"
    nav_icon = "house"

    def __init__(self, run: Runner | None, settings: Callable[[], Settings], parent=None):
        super().__init__(
            "Casa smart",
            "Trova i tuoi dispositivi Xiaomi, Aqara e Tapo, scopri cosa sono e leggine lo "
            "stato. Nulla viene modificato senza la tua conferma.",
            self.nav_icon,
            run,
            parent=parent,
        )
        self._settings = settings
        self.inventory: Inventory | None = None

        s1 = self.step(1, "Come funziona", SMART_HOME_STEPS)
        self.scan_btn = button("Cerca dispositivi", self.scan, "primary", "search")
        s1.add(row(self.scan_btn, None))

        s2 = self.step(
            2, "I tuoi dispositivi", "Clicca un dispositivo per sapere cos'è e cosa serve."
        )
        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(150)
        self.device_list.currentRowChanged.connect(self.show_device)
        s2.add(self.device_list)
        save_btn = button("Salva elenco…", self.save_inventory, icon_name="save")
        load_btn = button("Apri elenco…", self.load_inventory, icon_name="folder")
        s2.add(row(None, save_btn, load_btn))

        s3 = self.step(
            3,
            "Leggi lo stato o chiedi aiuto all'IA",
            "«Leggi stato» chiede token o account solo se servono e non li salva.",
        )
        self.read_btn = button("Leggi stato", self.read_state, icon_name="play")
        self.read_btn.setEnabled(False)
        self.guide_btn = button("Guida AI", self.run_guide, icon_name="help")
        self.guide_btn.setEnabled(False)
        s3.add(row(self.read_btn, self.guide_btn, None))
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setMinimumHeight(180)
        self.view.setPlainText("Premi «Cerca dispositivi» per iniziare.")
        s3.add(self.view)
        self.body.addWidget(self._build_advanced())
        self.busy_widgets = [self.scan_btn]

    def _build_advanced(self) -> QGroupBox:
        box = QGroupBox("Avanzate: invia un comando (può modificare il dispositivo)")
        box.setCheckable(True)
        box.setChecked(False)
        inner = QHBoxLayout(box)
        self.method_edit = QLineEdit()
        self.method_edit.setPlaceholderText("comando, es. get_status oppure app_start")
        self.params_edit = QLineEdit()
        self.params_edit.setPlaceholderText("parametri JSON, es. [] oppure {}")
        self.send_btn = button("Invia", self.send_command, "danger")
        inner.addWidget(self.method_edit, 2)
        inner.addWidget(self.params_edit, 2)
        inner.addWidget(self.send_btn)
        return box

    # --- Elenco ------------------------------------------------------------
    def scan(self) -> None:
        from drdeconstruct.smarthome.inventory import build_inventory, default_scanners

        self.device_list.clear()
        self.view.setPlainText("Ricerca in corso: può richiedere una decina di secondi…")
        self.run(
            lambda: build_inventory(default_scanners()),
            on_done=self.set_inventory,
            busy="Ricerca dispositivi smart home…",
        )

    def set_inventory(self, inv: Inventory) -> None:
        self.inventory = inv
        self.device_list.clear()
        self.device_list.addItems([self._label(d) for d in inv.devices])
        self.guide_btn.setEnabled(bool(inv.devices))
        found = (
            f"Trovati {len(inv.devices)} dispositivi. Clicca un dispositivo per i dettagli."
            if inv.devices
            else "Nessun dispositivo trovato. Controlla WiFi e Bluetooth e riprova."
        )
        errors = describe_errors(inv.errors)
        self.view.setPlainText(found + ("\n\n" + errors if errors else ""))
        if inv.devices:
            self.banner.success(
                f"Trovati {len(inv.devices)} dispositivi: cliccane uno nel passo 2."
            )
        else:
            self.banner.warning("Nessun dispositivo trovato. Controlla WiFi e Bluetooth e riprova.")

    @staticmethod
    def _label(dev: SmartDevice) -> str:
        from drdeconstruct.smarthome.presenter import ECOSYSTEM_NAMES

        name = dev.name or dev.model or dev.address or dev.identifier
        ready = " ✓ leggibile" if action_for(dev) is not None else ""
        return f"{ECOSYSTEM_NAMES[dev.ecosystem]} · {name}{ready}"

    def selected(self) -> SmartDevice | None:
        row = self.device_list.currentRow()
        if self.inventory is None or not 0 <= row < len(self.inventory.devices):
            return None
        return self.inventory.devices[row]

    def show_device(self, _row: int) -> None:
        dev = self.selected()
        if dev is None:
            return
        self.view.setPlainText(describe_device(dev))
        self.read_btn.setEnabled(action_for(dev) is not None)

    def save_inventory(self) -> None:
        if self.inventory is None:
            QMessageBox.information(self, "Niente da salvare", "Prima cerca i dispositivi.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salva elenco", "casa.json", "JSON (*.json)")
        if path:
            Path(path).write_text(self.inventory.to_json(), encoding="utf-8")

    def load_inventory(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Apri elenco", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.set_inventory(Inventory.from_dict(data))
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "File non valido", f"Non è un elenco valido: {exc}")

    # --- Lettura e comandi -------------------------------------------------
    def ask_text(self, title: str, label: str, secret: bool = False) -> str | None:
        mode = QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal
        text, ok = QInputDialog.getText(self, title, label, mode)
        return text.strip() if ok and text.strip() else None

    def confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.warning(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _job(self, dev: SmartDevice, method: str | None, params, confirmed: bool):
        """Prepara la lettura chiedendo le credenziali; None se l'utente annulla."""
        from drdeconstruct.smarthome.safety import CommandGuard

        guard = CommandGuard(confirmed=confirmed)
        action = action_for(dev)
        if action is Action.MIIO:
            token = self.ask_text(
                "Token Xiaomi",
                "Incolla il token del dispositivo (32 caratteri).\n"
                "Lo ricavi dal cloud Xiaomi, per esempio con «Xiaomi Cloud Tokens Extractor».",
                secret=True,
            )
            if token is None:
                return None
            from drdeconstruct.smarthome.miio import MiioClient

            name = method or ("get_status" if "vacuum" in dev.name.lower() else "miIO.info")
            return lambda: MiioClient(dev.address, token).send(name, params or [], guard)
        if action is Action.TAPO:
            user = self.ask_text("Account TP-Link", "Email dell'account dell'app Tapo:")
            if user is None:
                return None
            password = self.ask_text("Account TP-Link", "Password dell'account:", secret=True)
            if password is None:
                return None
            from drdeconstruct.smarthome.tapo import TapoClient

            name = method or "get_device_info"
            return lambda: TapoClient(dev.address, user, password).request(
                name, params or None, guard
            )
        if action is Action.VALETUDO:
            from drdeconstruct.smarthome.valetudo import read_robot

            return lambda: read_robot(dev.address)
        return None

    def read_state(self) -> None:
        dev = self.selected()
        if dev is None:
            return
        job = self._job(dev, None, None, confirmed=False)
        if job is not None:
            self.run(job, on_done=self._show_state, busy="Lettura dello stato…")

    def send_command(self) -> None:
        from drdeconstruct.smarthome.safety import MIIO_READ_ONLY, TAPO_READ_ONLY

        dev = self.selected()
        method = self.method_edit.text().strip()
        if dev is None or action_for(dev) in (None, Action.VALETUDO) or not method:
            QMessageBox.information(
                self,
                "Comando non disponibile",
                "Seleziona un dispositivo Xiaomi WiFi o Tapo leggibile e scrivi un comando.",
            )
            return
        try:
            params = json.loads(self.params_edit.text().strip() or "null")
        except ValueError:
            QMessageBox.warning(self, "Parametri non validi", "I parametri devono essere JSON.")
            return
        read_only = method in MIIO_READ_ONLY | TAPO_READ_ONLY
        if not read_only and not self.confirm(
            "Conferma il comando",
            f"Il comando «{method}» può cambiare lo stato del dispositivo "
            "(accenderlo, spegnerlo, muoverlo, cambiare impostazioni).\n\n"
            "Vuoi davvero inviarlo?",
        ):
            return
        job = self._job(dev, method, params, confirmed=not read_only)
        if job is not None:
            self.run(job, on_done=self._show_state, busy=f"Invio di {method}…")

    def _show_state(self, data) -> None:
        self.view.setPlainText("Stato del dispositivo:\n\n" + format_state(data))

    # --- Guida -------------------------------------------------------------
    def run_guide(self) -> None:
        from drdeconstruct.llm.factory import make_backend
        from drdeconstruct.smarthome.guide import SmartHomeAdvisor

        if self.inventory is None:
            return
        inv = self.inventory
        settings = self._settings()
        self.view.setPlainText("La guida sta analizzando i dispositivi trovati…")
        self.run(
            lambda: SmartHomeAdvisor(make_backend(settings)).advise(inv),
            on_done=lambda guide: self.view.setPlainText(format_guide(guide)),
            busy="Guida AI al lavoro…",
        )
