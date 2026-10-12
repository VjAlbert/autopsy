"""Finestra principale: barra in alto con il motore IA, navigazione a sinistra,
una pagina guidata per ogni modulo.

Pagine: Inizio, Spiega codice o dati, Decompila, Scheletro di codice, Sito web,
Dispositivi, Casa smart, Verifica qualità. Il motore IA si sceglie una volta
sola, in alto, e vale per tutte. I lavori lenti girano in un thread separato e
il loro avanzamento compare nel riquadro in cima alla pagina che li ha avviati.
"""

from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtCore import QSettings, QSize, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from drdeconstruct import __version__
from drdeconstruct.config import BACKENDS, Settings
from drdeconstruct.core.types import ArtifactKind
from drdeconstruct.gui import icons
from drdeconstruct.gui.components import Page, restyle
from drdeconstruct.gui.home_page import HomePage
from drdeconstruct.gui.pages import AnalysisPage, DecompilePage, DevicesPage, QualityPage, WebPage
from drdeconstruct.gui.scaffold_tab import ScaffoldTab
from drdeconstruct.gui.smarthome_tab import SmartHomeTab
from drdeconstruct.gui.theme import DARK_QSS
from drdeconstruct.gui.workers import Task

ENGINE_LABELS = {
    "claude-code": "Claude (il tuo abbonamento claude.ai)",
    "ollama": "Ollama (sul tuo PC, gratis, serve una buona GPU)",
    "api": "API Anthropic (a consumo, serve una chiave)",
}

REPO_URL = "https://github.com/VjAlbert/autopsy"


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings | None = None,
        persist: bool = False,
        check_system: bool = False,
    ):
        """`persist` ricorda motore e cartella di Ghidra tra un avvio e l'altro;
        `check_system` esegue subito il controllo del sistema (lo fa l'app vera)."""
        super().__init__()
        self._store = QSettings("DrDeconstruct", "DrDeconstruct") if persist else None
        self.settings = self._initial_settings(settings)
        self._task: Task | None = None
        self._owner: Page | None = None
        self.setWindowTitle("DrDeconstruct")
        self.setWindowIcon(icons.logo_icon())
        self.resize(1180, 800)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(DARK_QSS)

        self.home_page = HomePage()
        self.analysis_page = AnalysisPage(None, self._current_settings)
        self.decompile_page = DecompilePage(None, self._current_settings)
        self.scaffold_tab = ScaffoldTab(self._current_settings, self.statusBar())
        self.web_page = WebPage(None, self._current_settings)
        self.devices_page = DevicesPage(None, self._current_settings)
        self.smarthome_tab = SmartHomeTab(None, self._current_settings)
        self.quality_page = QualityPage(None, self._current_settings)
        self.page_by_key: dict[str, Page] = {
            "home": self.home_page,
            "analysis": self.analysis_page,
            "decompile": self.decompile_page,
            "scaffold": self.scaffold_tab,
            "web": self.web_page,
            "devices": self.devices_page,
            "smarthome": self.smarthome_tab,
            "quality": self.quality_page,
        }
        # Il runner sa quale pagina ha avviato il lavoro, per mostrarle l'avanzamento.
        for page in self.page_by_key.values():
            page.run = self._runner(page)

        self.pages = QStackedWidget()
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setFixedWidth(230)
        for page in self.page_by_key.values():
            self.pages.addWidget(page)
            QListWidgetItem(icons.icon(page.nav_icon), page.nav_title, self.nav)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_topbar())
        body = QHBoxLayout()
        body.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(8, 10, 8, 10)
        side.addWidget(self.nav, 1)
        version = QLabel(f"v{__version__} · uso lecito: software e dispositivi tuoi")
        version.setObjectName("hint")
        version.setWordWrap(True)
        side.addWidget(version)
        body.addWidget(sidebar)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self._build_menu()

        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 0)
        self._busy_bar.setFixedWidth(160)
        self._busy_bar.setTextVisible(False)
        self._busy_bar.hide()
        self.statusBar().addPermanentWidget(self._busy_bar)
        self.statusBar().showMessage("Pronto")

        self._connect_pages()
        self.nav.setCurrentRow(0)
        if check_system:
            self.run_checks()
        else:
            self._set_engine_state(None)

    # --- Costruzione --------------------------------------------------------
    def _initial_settings(self, settings: Settings | None) -> Settings:
        base = settings or Settings.from_env()
        if self._store is None:
            return base
        folder = self._store.value("ghidra_dir", "")
        if folder and not os.environ.get("GHIDRA_INSTALL_DIR"):
            os.environ["GHIDRA_INSTALL_DIR"] = str(folder)
        saved = self._store.value("backend", "")
        if settings is None and saved in BACKENDS and not os.environ.get("DRDEC_BACKEND"):
            return replace(base, backend=str(saved))
        return base

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(36))
        names = QVBoxLayout()
        names.setSpacing(0)
        brand = QLabel("DrDeconstruct")
        brand.setObjectName("brand")
        sub = QLabel("Autopsy · reverse engineering assistito dall'IA")
        sub.setObjectName("brandSub")
        names.addWidget(brand)
        names.addWidget(sub)
        layout.addWidget(logo)
        layout.addLayout(names)
        layout.addStretch()

        self.backend_box = QComboBox()
        for value in BACKENDS:
            self.backend_box.addItem(ENGINE_LABELS.get(value, value), value)
        self.backend_box.setCurrentIndex(max(self.backend_box.findData(self.settings.backend), 0))
        self.backend_box.setToolTip(
            "Il motore di intelligenza artificiale che spiega i risultati. "
            "Vale per tutte le schede."
        )
        self.backend_box.currentIndexChanged.connect(self._engine_changed)
        self.engine_dot = QLabel()
        self.engine_dot.setObjectName("engineDot")
        label = QLabel("Motore IA:")
        label.setObjectName("brandSub")
        layout.addWidget(label)
        layout.addWidget(self.backend_box)
        layout.addWidget(self.engine_dot)
        return bar

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("Aiuto")
        for text, slot in (
            ("Pagina iniziale", lambda: self.show_page("home")),
            ("Controlla il sistema", self.run_checks),
            ("Documentazione online", lambda: QDesktopServices.openUrl(QUrl(REPO_URL))),
            (
                "Segnala un problema",
                lambda: QDesktopServices.openUrl(QUrl(REPO_URL + "/issues/new/choose")),
            ),
            ("Informazioni su DrDeconstruct", self._about),
        ):
            action = QAction(text, self)
            action.triggered.connect(slot)
            menu.addAction(action)

    def _connect_pages(self) -> None:
        self.home_page.navigate.connect(self.show_page)
        self.home_page.recheck.connect(self.run_checks)
        self.decompile_page.open_scaffold.connect(lambda: self.show_page("scaffold"))
        self.decompile_page.ghidra_changed.connect(self._ghidra_changed)
        self.devices_page.explain.connect(self._explain)
        self.devices_page.open_binary.connect(self._open_binary)

    # --- Navigazione e collegamenti tra schede -----------------------------
    def show_page(self, key: str) -> None:
        self.nav.setCurrentRow(list(self.page_by_key).index(key))

    def current_page(self) -> Page:
        return self.pages.currentWidget()

    def _explain(self, kind: str, content: str) -> None:
        self.analysis_page.set_input(ArtifactKind(kind), content)
        self.show_page("analysis")

    def _open_binary(self, path: str) -> None:
        self.decompile_page.binary_edit.setText(path)
        self.decompile_page.banner.info(
            "Backup pronto: scegli il processore nel passo 3 e premi «Decompila»."
        )
        self.show_page("decompile")

    def _ghidra_changed(self, folder: str) -> None:
        if self._store is not None:
            self._store.setValue("ghidra_dir", folder)
        self.run_checks()

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "DrDeconstruct",
            f"<b>DrDeconstruct {__version__}</b><br>Reverse engineering assistito dall'IA, "
            "per software, firmware, dispositivi e siti web.<br><br>"
            f'Licenza MIT · <a href="{REPO_URL}">{REPO_URL}</a>',
        )

    # --- Motore IA e controllo del sistema --------------------------------
    def _backend(self) -> str:
        return self.backend_box.currentData() or self.settings.backend

    def _current_settings(self) -> Settings:
        return replace(self.settings, backend=self._backend())

    def _engine_changed(self) -> None:
        if self._store is not None:
            self._store.setValue("backend", self._backend())
        self.run_checks()

    def run_checks(self) -> None:
        """Controlli rapidi (percorsi e una richiesta locale): niente thread."""
        from drdeconstruct.doctor import run_checks

        checks = run_checks(self._current_settings())
        self.home_page.set_checks(checks)
        self.decompile_page.refresh_ghidra()
        self._set_engine_state(checks[0].ok)

    def _set_engine_state(self, ok: bool | None) -> None:
        text, state = {
            True: ("● pronto", "ok"),
            False: ("● da configurare", "bad"),
            None: ("● non controllato", "unknown"),
        }[ok]
        self.engine_dot.setText(text)
        self.engine_dot.setProperty("state", state)
        self.engine_dot.setToolTip("Dettagli nella pagina Inizio.")
        restyle(self.engine_dot)

    # --- Lavori in background ---------------------------------------------
    def _runner(self, owner: Page | None = None):
        def run(fn, on_done, busy: str, with_progress: bool = False) -> None:
            self._start(fn, on_done, busy, with_progress, owner)

        return run

    def _start(
        self, fn, on_done, busy: str, with_progress: bool = False, owner: Page | None = None
    ) -> None:
        if self._task and self._task.isRunning():
            message = "Aspetta: un'altra operazione è ancora in corso."
            self.statusBar().showMessage(message)
            if owner is not None:
                owner.banner.warning(message)
            return
        self._owner = owner
        if owner is not None:
            owner.set_busy(True, busy)
        self._busy_bar.show()
        self.statusBar().showMessage(busy)
        self._task = Task(fn, self, with_report=with_progress)
        self._task.progress.connect(self._progress)
        self._task.done.connect(lambda r: self._finish(on_done, r))
        self._task.failed.connect(self._fail)
        self._task.start()

    def _progress(self, msg) -> None:
        self.statusBar().showMessage(str(msg))
        if self._owner is not None:
            self._owner.banner.busy(str(msg))

    def _idle(self) -> Page | None:
        owner, self._owner = self._owner, None
        self._busy_bar.hide()
        if owner is not None:
            owner.set_busy(False)
        return owner

    def _finish(self, on_done, result) -> None:
        self._idle()
        self.statusBar().showMessage("Fatto")
        on_done(result)

    def _fail(self, message: str) -> None:
        owner = self._idle()
        self.statusBar().showMessage("Non è andata a buon fine: leggi il messaggio nella pagina.")
        if owner is not None:
            owner.banner.error(message)
        else:
            QMessageBox.critical(self, "Errore", message)

    def closeEvent(self, event) -> None:  # noqa: N802 - nome imposto da Qt
        if self._task and self._task.isRunning():
            self._task.wait(2000)
        super().closeEvent(event)
