"""Finestra principale: schede Software/Hardware, Decompila, Sito web, Dispositivi,
Casa smart."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from drdeconstruct.config import BACKENDS, Settings
from drdeconstruct.core.errors import BackendError
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind
from drdeconstruct.gui.scaffold_tab import ScaffoldTab
from drdeconstruct.gui.smarthome_tab import SmartHomeTab
from drdeconstruct.gui.theme import DARK_QSS
from drdeconstruct.gui.workers import Task

ENGINE_LABELS = {
    "claude-code": "Claude (il tuo abbonamento claude.ai)",
    "ollama": "Ollama (sul tuo PC, gratis, serve una buona GPU)",
    "api": "API Anthropic (a consumo, serve una chiave)",
}


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings.from_env()
        self._task: Task | None = None
        self.setWindowTitle("DrDeconstruct")
        self.resize(1040, 720)
        self.setStyleSheet(DARK_QSS)

        engine_row = QHBoxLayout()
        self.backend_box = QComboBox()
        for value in BACKENDS:
            self.backend_box.addItem(ENGINE_LABELS.get(value, value), value)
        self.backend_box.setCurrentIndex(max(self.backend_box.findData(self.settings.backend), 0))
        self.backend_box.setToolTip(
            "Il motore di intelligenza artificiale che spiega i risultati. "
            "Vale per tutte le schede."
        )
        engine_row.addWidget(QLabel("Motore IA:"))
        engine_row.addWidget(self.backend_box)
        engine_row.addStretch()

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_analysis_tab(), "Software / Hardware")
        self.tabs.addTab(self._build_decompile_tab(), "Decompila binario")
        self.scaffold_tab = ScaffoldTab(self.settings, self.statusBar())
        self.tabs.addTab(self.scaffold_tab, "Scheletro di codice")
        self.tabs.addTab(self._build_web_tab(), "Sito web")
        self.tabs.addTab(self._build_devices_tab(), "Dispositivi")
        self.smarthome_tab = SmartHomeTab(self._start, self._current_settings)
        self.tabs.addTab(self.smarthome_tab, "Casa smart")

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.addLayout(engine_row)
        outer.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Pronto")

    # --- Scheda analisi ---------------------------------------------------
    def _build_analysis_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        row = QHBoxLayout()
        self.kind_box = QComboBox()
        self.kind_box.addItems([k.value for k in ArtifactKind])
        self.arch_edit = QLineEdit()
        self.arch_edit.setPlaceholderText("architettura (es. mips32el)")
        row.addWidget(QLabel("Tipo:"))
        row.addWidget(self.kind_box)
        row.addWidget(self.arch_edit)
        layout.addLayout(row)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText(
            "Incolla qui pseudocodice, assembly, log o dump esadecimale…"
        )
        layout.addWidget(self.input_edit, 3)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Apri file…")
        load_btn.clicked.connect(self._load_file)
        self.run_btn = QPushButton("Analizza")
        self.run_btn.clicked.connect(self._run_analysis)
        btn_row.addWidget(load_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.run_btn)
        layout.addLayout(btn_row)

        self.output_view = QTextEdit()
        self.output_view.setReadOnly(True)
        layout.addWidget(self.output_view, 4)
        return w

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Apri file")
        if path:
            self.input_edit.setPlainText(Path(path).read_text(encoding="utf-8", errors="replace"))

    def _run_analysis(self) -> None:
        from dataclasses import replace

        from drdeconstruct.cli import build_orchestrator

        content = self.input_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Manca l'input", "Incolla o apri qualcosa da analizzare.")
            return
        settings = replace(self.settings, backend=self._backend())
        kind = ArtifactKind(self.kind_box.currentText())
        req = AnalysisRequest(
            content=content,
            domain=kind.domain,
            kind=kind,
            arch=self.arch_edit.text().strip() or None,
        )
        self._start(
            lambda: build_orchestrator(settings).run(req).model_dump(),
            on_done=lambda r: self.output_view.setPlainText(
                json.dumps(r, indent=2, ensure_ascii=False)
            ),
            busy="Analisi in corso…",
        )

    # --- Scheda decompilazione -------------------------------------------
    def _build_decompile_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(self._heading("Decompila un file binario con Ghidra"))
        layout.addWidget(
            self._hint(
                "Scegli un eseguibile o un firmware. Ghidra lo decompila e il risultato può "
                "essere analizzato dal modello. Per i firmware grezzi indica il processore "
                "(es. MIPS:LE:32:default). Richiede Ghidra installato (GHIDRA_INSTALL_DIR)."
            )
        )

        row = QHBoxLayout()
        self.binary_edit = QLineEdit()
        self.binary_edit.setPlaceholderText("percorso del file binario")
        pick = QPushButton("Scegli…")
        pick.clicked.connect(self._pick_binary)
        row.addWidget(self.binary_edit)
        row.addWidget(pick)
        layout.addLayout(row)

        opts = QHBoxLayout()
        self.proc_edit = QLineEdit()
        self.proc_edit.setPlaceholderText("processore (solo firmware grezzi)")
        self.analyze_chk = QPushButton("Analizza con il modello")
        self.analyze_chk.setCheckable(True)
        opts.addWidget(QLabel("Processore:"))
        opts.addWidget(self.proc_edit)
        opts.addWidget(self.analyze_chk)
        layout.addLayout(opts)

        self.decompile_btn = QPushButton("Decompila")
        self.decompile_btn.clicked.connect(self._run_decompile)
        layout.addWidget(self.decompile_btn)

        self.decompile_view = QTextEdit()
        self.decompile_view.setReadOnly(True)
        layout.addWidget(self.decompile_view, 1)
        return w

    def _pick_binary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Scegli un binario")
        if path:
            self.binary_edit.setText(path)

    def _run_decompile(self) -> None:
        from dataclasses import replace

        from drdeconstruct.preprocess.ghidra import GhidraExporter

        path = self.binary_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Manca il file", "Scegli un file binario.")
            return
        settings = replace(self.settings, backend=self._backend())
        processor = self.proc_edit.text().strip() or None
        analyze = self.analyze_chk.isChecked()

        def job():
            program = GhidraExporter().export(path, processor=processor)
            if not analyze:
                return program.as_c_source()
            from drdeconstruct.cli import analyze_functions, build_orchestrator
            from drdeconstruct.core.types import AnalysisRequest

            base = AnalysisRequest(content="", kind=ArtifactKind.PSEUDOCODE_C, arch=program.arch)
            funcs = [(f"{f.name}@{f.entry}", f.code) for f in program.functions]
            return json.dumps(
                analyze_functions(build_orchestrator(settings), base, funcs),
                indent=2,
                ensure_ascii=False,
            )

        self._start(job, on_done=self.decompile_view.setPlainText, busy="Ghidra al lavoro…")

    # --- Scheda sito web --------------------------------------------------
    def _build_web_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(self._heading("Studia un sito web"))
        layout.addWidget(
            self._hint(
                "1. Scrivi l'indirizzo della pagina.\n"
                '2. Premi "Analizza" per capire come è fatta, oppure "Salva copia sul PC" '
                "per averla in una cartella e modificarla.\n"
                "3. Dopo l'analisi, salva lo scheletro pulito per costruire la tua versione.\n\n"
                "Si scaricano solo i file pubblici, rispettando robots.txt; login e paywall "
                "non vengono aggirati. La copia è privata: non ripubblicarla. Per un sito tuo "
                "usa lo scheletro e contenuti tuoi."
            )
        )

        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Indirizzo della pagina, es. www.esempio.it")
        self.url_edit.returnPressed.connect(self._run_web)
        row.addWidget(self.url_edit, 1)
        layout.addLayout(row)

        opts = QHBoxLayout()
        self.web_struct_only = QCheckBox("Solo struttura, senza IA (veloce e gratis)")
        self.web_btn = QPushButton("Analizza")
        self.web_btn.setToolTip("Spiega sezioni, componenti, stile e tecnologie della pagina.")
        self.web_btn.clicked.connect(self._run_web)
        self.mirror_btn = QPushButton("Salva copia sul PC…")
        self.mirror_btn.setToolTip(
            "Scarica questa sola pagina con immagini, stili e caratteri in una cartella: "
            "la apri col browser anche senza internet e la modifichi per studiarla."
        )
        self.mirror_btn.clicked.connect(self._run_mirror)
        opts.addWidget(self.web_struct_only)
        opts.addStretch()
        opts.addWidget(self.web_btn)
        opts.addWidget(self.mirror_btn)
        layout.addLayout(opts)

        self.web_view = QTextEdit()
        self.web_view.setReadOnly(True)
        self.web_view.setPlaceholderText("Qui compare la spiegazione della pagina.")
        layout.addWidget(self.web_view, 1)

        out = QHBoxLayout()
        self.scaffold_btn = QPushButton("Salva scheletro della mia versione…")
        self.scaffold_btn.setToolTip(
            "Crea index.html, styles.css, script.js e NOTE.md con la struttura della pagina "
            "e testi segnaposto da sostituire con i tuoi. Richiede l'analisi con l'IA."
        )
        self.scaffold_btn.setEnabled(False)
        self.scaffold_btn.clicked.connect(self._save_scaffold)
        self.save_json_btn = QPushButton("Salva analisi (JSON)…")
        self.save_json_btn.setEnabled(False)
        self.save_json_btn.clicked.connect(self._save_web_json)
        self.open_folder_btn = QPushButton("Apri cartella")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._open_last_folder)
        out.addWidget(self.scaffold_btn)
        out.addWidget(self.save_json_btn)
        out.addStretch()
        out.addWidget(self.open_folder_btn)
        layout.addLayout(out)
        self._web_result = None
        self._last_folder: Path | None = None
        return w

    def _web_url(self) -> str | None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.information(
                self, "Manca l'indirizzo", "Scrivi l'indirizzo della pagina, es. www.esempio.it"
            )
            return None
        return url if "://" in url else "https://" + url

    def _run_web(self) -> None:
        from dataclasses import replace

        from drdeconstruct.cli import run_web

        url = self._web_url()
        if not url:
            return
        settings = (
            None
            if self.web_struct_only.isChecked()
            else replace(self.settings, backend=self._backend())
        )

        def job():
            try:
                return run_web(url, settings)
            except BackendError as exc:
                raise BackendError(
                    f"{exc}\n\nSuggerimento: scegli un altro motore in alto, oppure spunta "
                    '"Solo struttura, senza IA" per avere comunque la mappa della pagina.'
                ) from exc

        self.scaffold_btn.setEnabled(False)
        self.save_json_btn.setEnabled(False)
        busy = "Studio la pagina…" if settings is None else "Studio la pagina e la spiego con l'IA…"
        self._start(job, on_done=self._show_web, busy=busy)

    def _show_web(self, result) -> None:
        from drdeconstruct.web.scaffold import render_report

        snapshot, analysis = result
        self._web_result = result
        self.web_view.setMarkdown(render_report(snapshot, analysis))
        self.scaffold_btn.setEnabled(analysis is not None)
        self.save_json_btn.setEnabled(True)

    def _save_web_json(self) -> None:
        if not self._web_result:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva analisi", "analisi.json", "JSON (*.json)"
        )
        if not path:
            return
        snapshot, analysis = self._web_result
        payload = {"snapshot": snapshot.model_dump()}
        if analysis is not None:
            payload["analysis"] = analysis.model_dump()
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.statusBar().showMessage(f"Analisi salvata in {path}")

    def _save_scaffold(self) -> None:
        from drdeconstruct.web.scaffold import write_scaffold

        if not self._web_result or self._web_result[1] is None:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Scegli una cartella vuota per lo scheletro"
        )
        if not folder:
            return
        snapshot, analysis = self._web_result
        try:
            paths = write_scaffold(analysis, Path(folder), snapshot.css.breakpoints_px)
        except OSError as exc:
            QMessageBox.warning(self, "Non salvato", str(exc))
            return
        self._done_in_folder(
            Path(folder),
            f"Creati {len(paths)} file. Apri index.html con il browser e NOTE.md per il piano "
            "di lavoro; sostituisci i testi tra parentesi quadre con i tuoi.",
        )

    def _run_mirror(self) -> None:
        from drdeconstruct.web.mirror import mirror_page

        url = self._web_url()
        if not url:
            return
        folder = QFileDialog.getExistingDirectory(self, "Scegli una cartella vuota per la copia")
        if not folder:
            return
        target = Path(folder)

        def done(result) -> None:
            self._done_in_folder(
                target,
                f"Copia salvata: {len(result.saved)} file, {len(result.skipped)} saltati "
                "(elenco in LEGGIMI.txt). Apri index.html con il browser per vederla e "
                "modificarla. È una copia privata per studio: non ripubblicarla.",
            )

        self._start(
            lambda progress: mirror_page(url, target, progress=progress),
            on_done=done,
            busy="Salvo la pagina…",
            with_progress=True,
        )

    def _done_in_folder(self, folder: Path, message: str) -> None:
        self._last_folder = folder
        self.open_folder_btn.setEnabled(True)
        self.statusBar().showMessage(f"Salvato in {folder}")
        QMessageBox.information(self, "Fatto", message)

    def _open_last_folder(self) -> None:
        if self._last_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_folder)))

    # --- Scheda dispositivi ----------------------------------------------
    def _build_devices_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(self._heading("Dispositivi collegati"))
        layout.addWidget(
            self._hint(
                "Elenca ciò che è collegato via USB/seriale o vicino via Bluetooth. "
                "La lettura e la scrittura della memoria richiedono gli adattatori e "
                "avvengono sempre con backup e verifica."
            )
        )

        row = QHBoxLayout()
        for text, fn in (
            ("Scansiona USB", self._scan_usb),
            ("Porte seriali", self._scan_serial),
            ("Scansiona Bluetooth", self._scan_ble),
        ):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)

        self.device_list = QListWidget()
        layout.addWidget(self.device_list, 1)
        return w

    def _scan_usb(self) -> None:
        from drdeconstruct.acquisition.usb import list_usb_devices

        self._list_devices(list_usb_devices, "Scansione USB…")

    def _scan_serial(self) -> None:
        from drdeconstruct.acquisition.usb import list_serial_ports

        self._list_devices(list_serial_ports, "Lettura porte seriali…")

    def _scan_ble(self) -> None:
        from drdeconstruct.acquisition.bluetooth import scan_ble

        self._list_devices(scan_ble, "Scansione Bluetooth…")

    def _list_devices(self, fn, busy: str) -> None:
        self.device_list.clear()
        self._start(
            fn,
            on_done=lambda devs: self.device_list.addItems([str(d) for d in devs] or ["(nessuno)"]),
            busy=busy,
        )

    # --- Infrastruttura ---------------------------------------------------
    def _backend(self) -> str:
        return self.backend_box.currentData() or self.settings.backend

    def _current_settings(self) -> Settings:
        from dataclasses import replace

        return replace(self.settings, backend=self._backend())

    def _start(self, fn, on_done, busy: str, with_progress: bool = False) -> None:
        if self._task and self._task.isRunning():
            self.statusBar().showMessage("Aspetta: un'operazione è ancora in corso.")
            return
        self.run_btn.setEnabled(False) if hasattr(self, "run_btn") else None
        self.statusBar().showMessage(busy)
        self._task = Task(fn, self, with_report=with_progress)
        self._task.progress.connect(lambda msg: self.statusBar().showMessage(str(msg)))
        self._task.done.connect(lambda r: self._finish(on_done, r))
        self._task.failed.connect(self._fail)
        self._task.start()

    def _finish(self, on_done, result) -> None:
        self.statusBar().showMessage("Fatto")
        on_done(result)
        if hasattr(self, "run_btn"):
            self.run_btn.setEnabled(True)

    def _fail(self, message: str) -> None:
        self.statusBar().showMessage("Errore")
        if hasattr(self, "run_btn"):
            self.run_btn.setEnabled(True)
        QMessageBox.critical(self, "Errore", message)

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("heading")
        return label

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop)
        return label
