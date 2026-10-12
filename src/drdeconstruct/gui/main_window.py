"""Finestra principale di DrDeconstruct: schede Software, Hardware, Dispositivi, Casa smart."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
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
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind
from drdeconstruct.gui.smarthome_tab import SmartHomeTab
from drdeconstruct.gui.theme import DARK_QSS
from drdeconstruct.gui.workers import Task


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings.from_env()
        self._task: Task | None = None
        self.setWindowTitle("DrDeconstruct")
        self.resize(1040, 720)
        self.setStyleSheet(DARK_QSS)

        tabs = QTabWidget()
        tabs.addTab(self._build_analysis_tab(), "Software / Hardware")
        tabs.addTab(self._build_decompile_tab(), "Decompila binario")
        tabs.addTab(self._build_devices_tab(), "Dispositivi")
        self.smarthome_tab = SmartHomeTab(self._start, self._current_settings)
        tabs.addTab(self.smarthome_tab, "Casa smart")
        tabs.addTab(self._build_quality_tab(), "Verifica qualità")
        self.setCentralWidget(tabs)
        self.statusBar().showMessage("Pronto")

    # --- Scheda analisi ---------------------------------------------------
    def _build_analysis_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        row = QHBoxLayout()
        self.backend_box = QComboBox()
        self.backend_box.addItems(BACKENDS)
        self.backend_box.setCurrentText(self.settings.backend)
        self.kind_box = QComboBox()
        self.kind_box.addItems([k.value for k in ArtifactKind])
        self.arch_edit = QLineEdit()
        self.arch_edit.setPlaceholderText("architettura (es. mips32el)")
        row.addWidget(QLabel("Motore:"))
        row.addWidget(self.backend_box)
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

        from drdeconstruct.cli import analyze_functions, build_engine
        from drdeconstruct.preprocess.chunker import split_c_functions

        content = self.input_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Manca l'input", "Incolla o apri qualcosa da analizzare.")
            return
        settings = replace(self.settings, backend=self.backend_box.currentText())
        kind = ArtifactKind(self.kind_box.currentText())
        req = AnalysisRequest(
            content=content,
            domain=kind.domain,
            kind=kind,
            arch=self.arch_edit.text().strip() or None,
        )
        # Più funzioni C incollate insieme: una alla volta, con nomi coerenti tra loro.
        chunks = split_c_functions(content) if kind is ArtifactKind.PSEUDOCODE_C else []

        def job():
            llm, orch = build_engine(settings)
            if len(chunks) > 1:
                return analyze_functions(orch, req, [(c.name, c.code) for c in chunks], llm=llm)
            return orch.run(req).model_dump()

        busy = (
            f"Analisi di {len(chunks)} funzioni, con nomi coerenti tra loro…"
            if len(chunks) > 1
            else "Analisi in corso…"
        )
        self._start(
            job,
            on_done=lambda r: self.output_view.setPlainText(
                json.dumps(r, indent=2, ensure_ascii=False)
            ),
            busy=busy,
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
        settings = replace(self.settings, backend=self.backend_box.currentText())
        processor = self.proc_edit.text().strip() or None
        analyze = self.analyze_chk.isChecked()

        def job():
            program = GhidraExporter().export(path, processor=processor)
            if not analyze:
                return program.as_c_source()
            from drdeconstruct.cli import analyze_functions, build_engine
            from drdeconstruct.core.types import AnalysisRequest

            base = AnalysisRequest(content="", kind=ArtifactKind.PSEUDOCODE_C, arch=program.arch)
            funcs = [(f"{f.name}@{f.entry}", f.code) for f in program.functions]
            llm, orch = build_engine(settings)
            return json.dumps(
                analyze_functions(orch, base, funcs, llm=llm),
                indent=2,
                ensure_ascii=False,
            )

        self._start(job, on_done=self.decompile_view.setPlainText, busy="Ghidra al lavoro…")

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

    # --- Scheda verifica qualità ------------------------------------------
    def _build_quality_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(self._heading("Quanto sono buoni i nomi proposti?"))
        layout.addWidget(
            self._hint(
                "Fa analizzare al modello alcune funzioni di esempio di cui conosciamo i nomi "
                "veri (CRC32, strlen, checksum, driver UART…) e conta quanti nomi indovina. "
                "Utile per scegliere il motore o il modello migliore. Usa il modello davvero: "
                "consuma un po' del tuo abbonamento o credito e richiede qualche minuto."
            )
        )
        row = QHBoxLayout()
        self.quality_backend = QComboBox()
        self.quality_backend.addItems(BACKENDS)
        self.quality_backend.setCurrentText(self.settings.backend)
        self.quality_global = QCheckBox("Nomi coerenti tra funzioni (consigliato)")
        self.quality_global.setChecked(True)
        row.addWidget(QLabel("Motore:"))
        row.addWidget(self.quality_backend)
        row.addWidget(self.quality_global)
        row.addStretch()
        layout.addLayout(row)

        self.quality_btn = QPushButton("Avvia verifica")
        self.quality_btn.clicked.connect(self._run_quality)
        layout.addWidget(self.quality_btn)

        self.quality_view = QPlainTextEdit()
        self.quality_view.setReadOnly(True)
        layout.addWidget(self.quality_view, 1)
        return w

    def _run_quality(self) -> None:
        from dataclasses import replace

        from drdeconstruct.cli import analyze_functions, build_engine
        from drdeconstruct.evaluation import load_cases, report, run_case

        settings = replace(self.settings, backend=self.quality_backend.currentText())
        use_global = self.quality_global.isChecked()

        def job():
            llm, orch = build_engine(settings)
            names_llm = llm if use_global else None
            results = [
                run_case(case, lambda req, fns: analyze_functions(orch, req, fns, llm=names_llm))
                for case in load_cases()
            ]
            return report(results)

        self._start(job, on_done=self.quality_view.setPlainText, busy="Verifica in corso…")

    # --- Infrastruttura ---------------------------------------------------
    def _current_settings(self) -> Settings:
        from dataclasses import replace

        return replace(self.settings, backend=self.backend_box.currentText())

    def _start(self, fn, on_done, busy: str) -> None:
        if self._task and self._task.isRunning():
            return
        self.run_btn.setEnabled(False) if hasattr(self, "run_btn") else None
        self.statusBar().showMessage(busy)
        self._task = Task(fn, self)
        self._task.done.connect(lambda r: self._finish(on_done, r))
        self._task.failed.connect(self._fail)
        self._task.start()

    def _finish(self, on_done, result) -> None:
        on_done(result)
        self.statusBar().showMessage("Fatto")
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
