"""Schermata iniziale: controllo del sistema e scelta di cosa fare.

Chi apre il programma per la prima volta vede subito se il motore IA è pronto
(e come sistemarlo con un clic), poi una griglia di schede con una frase
ciascuna su a cosa servono.
"""

from __future__ import annotations

from PySide6.QtCore import QProcess, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from drdeconstruct import __version__
from drdeconstruct.doctor import Check
from drdeconstruct.gui import icons
from drdeconstruct.gui.components import Page, button, label, row
from drdeconstruct.gui.theme import ACCENT, MUTED, SUCCESS, WARNING

# Chiave della pagina, icona, titolo e descrizione di ogni scheda.
TILES = [
    ("analysis", "code", "Spiega codice o dati", "Pseudocodice, assembly, dump, log seriali."),
    ("decompile", "chip", "Decompila un programma", "Da .exe o firmware a codice C con Ghidra."),
    ("scaffold", "layers", "Scheletro di codice", "Un codice riscritto e ordinato da completare."),
    ("web", "globe", "Studia un sito web", "Struttura, copia privata, scheletro pulito."),
    ("devices", "usb", "Dispositivi collegati", "USB, seriale, Bluetooth, backup della flash."),
    ("smarthome", "house", "Casa smart", "Xiaomi, Aqara e Tapo: trova e leggi i dispositivi."),
    ("quality", "gauge", "Verifica qualità", "Quanto è bravo il motore IA a dare i nomi."),
]


class HomePage(Page):
    nav_title = "Inizio"
    nav_icon = "home"
    navigate = Signal(str)
    recheck = Signal()

    def __init__(self, parent=None):
        super().__init__(
            "Benvenuto in DrDeconstruct",
            f"Reverse engineering spiegato in parole semplici · versione {__version__}",
            self.nav_icon,
            parent=parent,
        )
        s1 = self.step(
            1,
            "Controlla che tutto sia pronto",
            "Il motore IA si sceglie in alto a destra. Ghidra e flashrom servono solo per "
            "alcune schede: puoi installarli dopo.",
        )
        self.checks_box = QVBoxLayout()
        self.checks_box.setSpacing(6)
        s1.add(self.checks_box)
        self.check_btn = button("Controlla di nuovo", self.recheck.emit, icon_name="refresh")
        self.install_btn = button(
            "Installa Claude Code",
            self.install_claude,
            "primary",
            "play",
            "Apre una finestra che esegue l'installer ufficiale di Claude Code.",
        )
        self.login_btn = button(
            "Accedi a Claude",
            self.login_claude,
            icon_name="play",
            tooltip="Apre una finestra con Claude Code: segui le istruzioni per il login.",
        )
        s1.add(row(self.check_btn, self.install_btn, self.login_btn, None))
        self.install_btn.hide()
        self.login_btn.hide()
        self.busy_widgets = [self.check_btn]
        self.set_checks([])

        s2 = self.step(2, "Scegli cosa vuoi fare", "Ogni scheda ti guida passo per passo.")
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles: dict[str, QPushButton] = {}
        for i, (key, icon_name, title, text) in enumerate(TILES):
            tile = QPushButton(f"{title}\n{text}")
            tile.setObjectName("tile")
            tile.setIcon(icons.icon(icon_name, ACCENT))
            tile.setIconSize(QSize(28, 28))
            tile.setMinimumHeight(70)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.clicked.connect(lambda _c=False, k=key: self.navigate.emit(k))
            grid.addWidget(tile, i // 2, i % 2)
            self.tiles[key] = tile
        s2.add(grid)

        self.body.addWidget(
            label(
                "Usa DrDeconstruct su software e dispositivi tuoi o open source, per "
                "interoperabilità, studio o ricerca di sicurezza. Non serve ad aggirare licenze.",
                "hint",
            )
        )
        self.body.addStretch()

    def set_checks(self, checks: list[Check]) -> None:
        while self.checks_box.count():
            item = self.checks_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not checks:
            self.checks_box.addWidget(label("Controllo in corso…", "hint"))
            return
        for check in checks:
            self.checks_box.addWidget(self._check_row(check))
        engine = checks[0]
        self.install_btn.setVisible(engine.key == "claude-code" and not engine.ok)
        self.login_btn.setVisible(engine.key == "claude-code" and engine.ok)
        if engine.ok:
            self.banner.success(
                f"Il motore IA è pronto ({engine.title}). Scegli cosa fare qui sotto."
            )
        else:
            self.banner.warning(f"Il motore IA non è ancora pronto: {engine.detail} {engine.fix}")

    def _check_row(self, check: Check) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        name = "check" if check.ok else "alert"
        color = SUCCESS if check.ok else (MUTED if check.optional else WARNING)
        pic = QLabel()
        pic.setPixmap(icons.pixmap(name, 18, color))
        pic.setFixedSize(20, 20)
        title = label(f"<b>{check.title}</b> — {check.detail}")
        top = row(pic, title)
        top.setStretch(1, 1)
        layout.addLayout(top)
        if not check.ok and (check.fix or check.link):
            parts = [label(check.fix, "hint")] if check.fix else []
            if check.link:
                parts.append(button("Apri la pagina", lambda u=check.link: open_url(u), "link"))
            fix = row(*parts, None)
            fix.setContentsMargins(28, 0, 0, 0)
            layout.addLayout(fix)
        return box

    def install_claude(self) -> None:
        from drdeconstruct.doctor import CLAUDE_DOCS, install_command

        answer = QMessageBox.question(
            self,
            "Installa Claude Code",
            "Si apre una finestra che scarica ed esegue l'installer ufficiale di Claude Code "
            f"(istruzioni su {CLAUDE_DOCS}).\n\nAl termine premi «Accedi a Claude» e poi "
            "«Controlla di nuovo». Vuoi continuare?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._launch(install_command())

    def login_claude(self) -> None:
        from drdeconstruct.doctor import login_command

        self._launch(login_command())
        self.banner.info(
            "Nella finestra appena aperta segui le istruzioni: si apre il browser per il login "
            "con il tuo account claude.ai. Poi chiudi la finestra e torna qui."
        )

    def _launch(self, argv: list[str]) -> None:
        if not QProcess.startDetached(argv[0], argv[1:]):
            self.banner.error(
                "Non riesco ad aprire la finestra del terminale. Segui le istruzioni nella "
                "pagina che si apre."
            )
            from drdeconstruct.doctor import CLAUDE_DOCS

            open_url(CLAUDE_DOCS)


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))
