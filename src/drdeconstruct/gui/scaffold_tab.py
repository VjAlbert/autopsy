"""Scheda "Scheletro di codice": passaggi guidati e anteprima dal vivo.

A sinistra l'operatore sceglie cosa trasformare, il linguaggio e la cartella
(il motore è quello della barra in alto); a destra vede lo scheletro formarsi
funzione per funzione mentre il modello lavora, e può fermarlo tenendo ciò che
è già pronto.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from drdeconstruct.config import Settings
from drdeconstruct.gui.components import Page, StepCard, button, row
from drdeconstruct.gui.workers import Task
from drdeconstruct.software.scaffold import DEFAULT_LANGUAGE, Language

LANGUAGE_LABELS = {
    Language.C: "C (consigliato: il più vicino al decompilato)",
    Language.PYTHON: "Python (più facile da leggere)",
    Language.RUST: "Rust",
}


def default_folder(stem: str = "scheletro") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / "DrDeconstruct" / "scheletri" / f"{stem}-{stamp}"


class ScaffoldTab(Page):
    nav_title = "Scheletro di codice"
    nav_icon = "layers"

    def __init__(
        self,
        settings: Settings | Callable[[], Settings],
        status_bar: QStatusBar | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(
            "Scheletro di codice",
            "Trasforma un programma decompilato in un codice ordinato da completare: nomi "
            "chiari, funzioni descritte e, dentro, i passi da scrivere.",
            self.nav_icon,
            scroll=False,
            parent=parent,
        )
        # Il motore è quello scelto nella barra in alto (vale per tutte le schede).
        self._settings = settings if callable(settings) else (lambda: settings)
        self._status_bar = status_bar
        self._task: Task | None = None
        self._stop_requested = False
        self._source_name = "scheletro"
        self._items: dict[str, int] = {}
        self.result_dir: Path | None = None

        splitter = QSplitter(Qt.Orientation.Horizontal)
        steps = QScrollArea()
        steps.setWidgetResizable(True)
        steps.setWidget(self._build_steps())
        splitter.addWidget(steps)
        splitter.addWidget(self._build_preview())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        self.body.addWidget(splitter, 1)

    # --- Passaggi guidati ------------------------------------------------
    def _build_steps(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)

        # 1. Sorgente
        s1 = StepCard(1, "Cosa vuoi trasformare?")
        self.mode_binary = QRadioButton("Un programma o un firmware (.exe, .bin, .elf…)")
        self.mode_text = QRadioButton("Codice già decompilato (Ghidra/IDA) o assembly")
        self.mode_binary.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.mode_binary)
        group.addButton(self.mode_text)
        s1.add(self.mode_binary).add(self.mode_text)

        self.source_stack = QStackedWidget()
        self.source_stack.addWidget(self._binary_page())
        self.source_stack.addWidget(self._text_page())
        self.mode_binary.toggled.connect(
            lambda on: self.source_stack.setCurrentIndex(0 if on else 1)
        )
        s1.add(self.source_stack)
        layout.addWidget(s1)

        # 2. Linguaggio
        s2 = StepCard(2, "In che linguaggio lo vuoi?")
        self.lang_box = QComboBox()
        for lang, text in LANGUAGE_LABELS.items():
            self.lang_box.addItem(text, lang.value)
        self.lang_box.setCurrentIndex(list(LANGUAGE_LABELS).index(DEFAULT_LANGUAGE))
        s2.add(self.lang_box)
        layout.addWidget(s2)

        # 3. Cartella
        s3 = StepCard(
            3, "Dove salvarlo?", "Usa una cartella nuova o vuota: niente viene sovrascritto."
        )
        self.folder_edit = QLineEdit(str(default_folder()))
        s3.add(row(self.folder_edit, button("Cambia…", self._pick_folder, icon_name="folder")))
        layout.addWidget(s3)

        # 4. Avvio
        s4 = StepCard(
            4,
            "Avvia",
            "Usa il motore IA scelto in alto. «Ferma» si ferma dopo la funzione in corso e "
            "salva ciò che è pronto.",
        )
        self.run_btn = button("Genera scheletro", self.start, "primary", "play")
        self.stop_btn = button("Ferma", self.stop, "danger", "stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("Si ferma dopo la funzione in corso e salva ciò che è pronto.")
        s4.add(row(self.run_btn, self.stop_btn, None))
        layout.addWidget(s4)
        layout.addWidget(
            _label(
                "Non è una copia del programma: è un punto di partenza per capirlo e rifarlo "
                "a modo tuo. Usalo su software tuo o open source.",
                "hint",
            )
        )
        layout.addStretch()
        return w

    def _binary_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self.binary_edit = QLineEdit()
        self.binary_edit.setPlaceholderText("scegli il file del programma")
        layout.addLayout(
            row(self.binary_edit, button("Scegli file…", self._pick_binary, icon_name="folder"))
        )
        self.processor_edit = QLineEdit()
        self.processor_edit.setPlaceholderText(
            "processore, solo per firmware grezzi (es. MIPS:LE:32:default)"
        )
        layout.addWidget(self.processor_edit)
        layout.addWidget(
            _label(
                "Serve Ghidra installato (gratuito). Se non sai il processore lascia vuoto.",
                "hint",
            )
        )
        return w

    def _text_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self.code_input = QPlainTextEdit()
        self.code_input.setPlaceholderText("Incolla qui il codice decompilato o l'assembly…")
        layout.addWidget(self.code_input)
        self.asm_check = QCheckBox("È assembly (non C)")
        load = button("Apri file di testo…", self._load_text, icon_name="folder")
        layout.addLayout(row(load, None, self.asm_check))
        return w

    # --- Anteprima dal vivo ----------------------------------------------
    def _build_preview(self) -> QWidget:
        w = QFrame()
        w.setObjectName("card")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(_label("Anteprima dal vivo", "stepTitle"))
        self.status_label = _label("Segui i passi a sinistra e premi «Genera scheletro».", "hint")
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.function_list = QListWidget()
        self.function_list.setMaximumHeight(140)
        layout.addWidget(self.function_list)

        self.preview = QPlainTextEdit()
        self.preview.setObjectName("code")
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setPlaceholderText("Qui vedrai il codice formarsi, una funzione alla volta.")
        layout.addWidget(self.preview, 1)

        self.open_btn = button(
            "Apri la cartella dello scheletro", self._open_folder, icon_name="folder"
        )
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn)
        return w

    # --- Azioni ----------------------------------------------------------
    def _pick_binary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Scegli il programma o il firmware")
        if path:
            self.binary_edit.setText(path)
            self._set_source_name(Path(path).stem)

    def _load_text(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Apri il codice decompilato")
        if path:
            self.code_input.setPlainText(Path(path).read_text(encoding="utf-8", errors="replace"))
            self._set_source_name(Path(path).stem)

    def _set_source_name(self, stem: str) -> None:
        self._source_name = stem
        self.folder_edit.setText(str(default_folder(stem)))

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Cartella (vuota) per lo scheletro")
        if folder:
            self.folder_edit.setText(folder)

    def _open_folder(self) -> None:
        if self.result_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_dir)))

    def stop(self) -> None:
        self._stop_requested = True
        self.stop_btn.setEnabled(False)
        self._status("Mi fermo dopo la funzione in corso e salvo ciò che è pronto…")

    def start(self) -> None:
        from drdeconstruct.cli import run_scaffold
        from drdeconstruct.core.errors import DrDeconstructError
        from drdeconstruct.preprocess.chunker import split_c_functions
        from drdeconstruct.preprocess.ghidra import GhidraExporter
        from drdeconstruct.software.scaffold import SourceFunction

        if self._task and self._task.isRunning():
            return
        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            self.banner.warning("Manca la cartella: indica dove salvare lo scheletro (passo 3).")
            return
        folder = Path(folder_text).expanduser()
        if folder.exists() and any(folder.iterdir()):
            self.banner.warning(
                "La cartella scelta contiene già dei file. Scegline una vuota o nuova "
                "per non sovrascrivere nulla (passo 3)."
            )
            return

        binary = self.mode_binary.isChecked()
        path = self.binary_edit.text().strip()
        code = self.code_input.toPlainText().strip()
        if binary and not path:
            self.banner.warning("Manca il file: premi «Scegli file…» nel passo 1.")
            return
        if not binary and not code:
            self.banner.warning("Manca il codice: incollalo nel passo 1 o apri un file di testo.")
            return

        settings = self._settings()
        lang = self.lang_box.currentData()
        processor = self.processor_edit.text().strip() or None
        source_name = self._source_name
        is_asm = self.asm_check.isChecked()

        def job(report):
            arch, source = None, source_name
            if binary:
                report(("stage", "Ghidra sta decompilando il file: può volerci qualche minuto…"))
                program = GhidraExporter().export(path, processor=processor)
                functions = [SourceFunction(f.name, f.code, f.entry) for f in program.functions]
                arch, source = program.arch, program.program
                if not functions:
                    raise DrDeconstructError(
                        "Ghidra non ha trovato funzioni. Se è un firmware grezzo, indica il "
                        "processore."
                    )
            else:
                chunks = [] if is_asm else split_c_functions(code)
                functions = [SourceFunction(c.name, c.code) for c in chunks] or [
                    SourceFunction("funzione", code)
                ]
            report(("functions", [f.name for f in functions]))
            return run_scaffold(
                settings,
                functions,
                folder,
                lang,
                arch,
                source=source,
                progress=lambda i, n, name: report(("start", i, n, name)),
                on_update=lambda module: report(("module", module)),
                should_stop=lambda: self._stop_requested,
            )

        self._stop_requested = False
        self.result_dir = None
        self.open_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.function_list.clear()
        self.preview.clear()
        self._items = {}
        self.progress.setRange(0, 0)  # in attesa
        self.banner.busy("Generazione in corso: segui l'anteprima a destra.")
        self._status("Preparo il lavoro…")

        self._task = Task(job, self, with_report=True)
        self._task.progress.connect(self._on_progress)
        self._task.done.connect(self._on_done)
        self._task.failed.connect(self._on_failed)
        self._task.start()

    # --- Aggiornamenti dal thread di lavoro -------------------------------
    def _on_progress(self, msg: tuple) -> None:
        from drdeconstruct.software.scaffold import preview

        kind = msg[0]
        if kind == "stage":
            self.progress.setRange(0, 0)
            self._status(msg[1])
        elif kind == "functions":
            names = msg[1]
            self._items = {name: i for i, name in enumerate(names)}
            self.function_list.addItems([f"○ {name}" for name in names])
            self.progress.setRange(0, len(names))
            self.progress.setValue(0)
        elif kind == "start":
            _, i, n, name = msg
            self._status(f"Funzione {i} di {n}: il modello sta ricostruendo {name}…")
            self._mark(name, f"✱ {name} (in corso)")
        elif kind == "module":
            module = msg[1]
            for sk in module.functions:
                self._mark(sk.original_name, f"✓ {sk.original_name} → {sk.name}")
            for name in module.failed:
                self._mark(name, f"✗ {name} (non riuscita, vedi NOTE.md)")
            self.progress.setValue(len(module.functions) + len(module.failed))
            self.preview.setPlainText(preview(module))
            self.preview.moveCursor(QTextCursor.MoveOperation.End)

    def _mark(self, name: str, text: str) -> None:
        row = self._items.get(name)
        if row is not None:
            self.function_list.item(row).setText(text)
            self.function_list.scrollToItem(self.function_list.item(row))

    def _on_done(self, result) -> None:
        module, paths = result
        self.result_dir = paths[0].parent
        self._reset_buttons()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        failed = f", {len(module.failed)} non riuscite" if module.failed else ""
        stopped = " (interrotto)" if self._stop_requested else ""
        self._status(
            f"Fatto{stopped}: {len(module.functions)} funzioni{failed}. "
            f"Salvato in {self.result_dir}"
        )
        self.open_btn.setEnabled(True)
        self.banner.success(
            f"Scheletro pronto in {self.result_dir}. Premi «Apri la cartella dello scheletro»."
        )

    def _on_failed(self, message: str) -> None:
        self._reset_buttons()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._status("Non è andata a buon fine.")
        self.banner.error(f"Scheletro non generato. {message}")

    def _reset_buttons(self) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _status(self, text: str) -> None:
        self.status_label.setText(text)
        if self._status_bar is not None:
            self._status_bar.showMessage(text)


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label
