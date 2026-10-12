"""Scheda "Porta il tuo codice": traduce il sorgente dell'utente in Rust (o altro).

A sinistra i passaggi guidati: quale codice, in che linguaggio, dove salvarlo,
se compilarlo. A destra la traduzione si forma pezzo per pezzo, con accanto la
checklist di cosa controllare. «Ferma» tiene ciò che è già tradotto.
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
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from drdeconstruct.config import Settings
from drdeconstruct.gui.components import Page, StepCard, button, row
from drdeconstruct.gui.theme import ACCENT
from drdeconstruct.gui.workers import Task
from drdeconstruct.software.port_source import SOURCE_LANGUAGE_LABELS

TARGET_LABELS = {
    "rust": "Rust (consigliato)",
    "python": "Python",
    "c": "C",
}

EXPECTATIONS = (
    "Cosa aspettarti: il programma traduce il tuo codice un pezzo alla volta, con le "
    "funzioni complete, e ti dà una checklist di cosa controllare. Su codice semplice "
    "spesso compila subito; su codice complesso resta del lavoro a mano. Prima di usarlo "
    "davvero, provalo con gli stessi input dell'originale. Usalo sul codice che hai scritto tu."
)


def default_folder(stem: str = "porting") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / "DrDeconstruct" / "porting" / f"{stem}-{stamp}"


class PortTab(Page):
    nav_title = "Porta il tuo codice"
    nav_icon = "swap"

    def __init__(
        self,
        settings: Settings | Callable[[], Settings],
        status_bar: QStatusBar | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(
            "Porta il tuo codice in un altro linguaggio",
            "Traduce il codice che hai scritto tu in Rust (o Python, C), con le funzioni "
            "complete e una checklist di cosa verificare.",
            self.nav_icon,
            scroll=False,
            parent=parent,
        )
        self._settings = settings if callable(settings) else (lambda: settings)
        self._status_bar = status_bar
        self._task: Task | None = None
        self._stop_requested = False
        self._source_name = "porting"
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
        self.refresh_checker()

    # --- Passaggi guidati ------------------------------------------------
    def _build_steps(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)
        layout.addWidget(_label(EXPECTATIONS, "hint"))

        s1 = StepCard(1, "Quale codice vuoi tradurre?")
        self.mode_file = QRadioButton("Un file")
        self.mode_folder = QRadioButton("Una cartella (tutto il progetto)")
        self.mode_text = QRadioButton("Incollo il codice qui")
        self.mode_file.setChecked(True)
        group = QButtonGroup(self)
        for b in (self.mode_file, self.mode_folder, self.mode_text):
            group.addButton(b)
            s1.add(b)
        # Le pagine nascoste non devono occupare spazio: la scheda resta compatta.
        self.source_stack = QStackedWidget()
        self.source_stack.addWidget(self._path_page())
        self.source_stack.addWidget(self._text_page())
        self.source_stack.currentChanged.connect(self._fit_stack)
        self.mode_text.toggled.connect(lambda on: self.source_stack.setCurrentIndex(int(on)))
        self._fit_stack(0)
        for b in (self.mode_file, self.mode_folder):
            b.toggled.connect(lambda _on: self._mode_changed())
        s1.add(self.source_stack)
        self.source_summary = _label("", "hint")
        s1.add(self.source_summary)
        layout.addWidget(s1)

        s2 = StepCard(2, "In che linguaggio lo vuoi?")
        self.lang_box = QComboBox()
        for value, text in TARGET_LABELS.items():
            self.lang_box.addItem(text, value)
        self.lang_box.currentIndexChanged.connect(lambda _i: self.refresh_checker())
        s2.add(self.lang_box)
        layout.addWidget(s2)

        s3 = StepCard(
            3, "Dove salvarlo?", "Usa una cartella nuova o vuota: niente viene sovrascritto."
        )
        self.folder_edit = QLineEdit(str(default_folder()))
        s3.add(row(self.folder_edit, button("Cambia…", self._pick_folder, icon_name="folder")))
        layout.addWidget(s3)

        s4 = StepCard(4, "Controllo automatico")
        self.check_box = QCheckBox("Compila il risultato e fai correggere gli errori al modello")
        self.check_box.setChecked(True)
        self.checker_label = _label("", "hint")
        s4.add(self.check_box).add(self.checker_label)
        layout.addWidget(s4)

        s5 = StepCard(
            5, "Avvia", "Usa il motore IA scelto in alto. «Ferma» tiene ciò che è già tradotto."
        )
        self.run_btn = button("Traduci", self.start, "primary", "play")
        self.stop_btn = button("Ferma", self.stop, "danger", "stop")
        self.stop_btn.setEnabled(False)
        s5.add(row(self.run_btn, self.stop_btn, None))
        layout.addWidget(s5)
        layout.addStretch()
        return w

    def _path_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("scegli il file del tuo codice")
        self.path_edit.editingFinished.connect(self._summarize)
        layout.addLayout(
            row(self.path_edit, button("Scegli…", self._pick_source, icon_name="folder"))
        )
        return w

    def _text_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self.code_input = QPlainTextEdit()
        self.code_input.setPlaceholderText("Incolla qui il tuo codice…")
        layout.addWidget(self.code_input)
        self.source_lang_box = QComboBox()
        self.source_lang_box.addItem("Riconosci da solo", "")
        for value, text in SOURCE_LANGUAGE_LABELS.items():
            self.source_lang_box.addItem(text, value)
        layout.addLayout(row(QLabel("Linguaggio del codice:"), self.source_lang_box, None))
        return w

    # --- Anteprima -------------------------------------------------------
    def _build_preview(self) -> QWidget:
        w = QFrame()
        w.setObjectName("card")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(_label("Anteprima dal vivo", "stepTitle"))
        self.status_label = _label("Segui i passi a sinistra e premi «Traduci».", "hint")
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.unit_list = QListWidget()
        self.unit_list.setMaximumHeight(140)
        layout.addWidget(self.unit_list)

        self.tabs = QTabWidget()
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("code")
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setPlaceholderText("Qui vedrai il codice tradotto, un pezzo alla volta.")
        self.checklist = QTextBrowser()
        self.checklist.setOpenExternalLinks(True)
        self.checklist.document().setDefaultStyleSheet(f"a {{ color: {ACCENT}; }}")
        self.checklist.setPlaceholderText("Qui comparirà la lista di cosa controllare.")
        self.tabs.addTab(self.preview, "Codice")
        self.tabs.addTab(self.checklist, "Checklist")
        layout.addWidget(self.tabs, 1)

        self.open_btn = button(
            "Apri la cartella del porting", self._open_folder, icon_name="folder"
        )
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn)
        return w

    # --- Azioni ----------------------------------------------------------
    def refresh_checker(self) -> None:
        from drdeconstruct.software.port import checker_available

        target = self.lang_box.currentData()
        tool = checker_available(target)
        if tool:
            self.checker_label.setText(f"Pronto: userò {tool}.")
        elif target == "rust":
            self.checker_label.setText(
                "Rust non è installato: la traduzione funziona lo stesso, ma senza controllo. "
                "Per attivarlo installa Rust da rustup.rs (gratuito)."
            )
        else:
            self.checker_label.setText("Compilatore non trovato: salterò il controllo.")

    def _fit_stack(self, index: int) -> None:
        for i in range(self.source_stack.count()):
            policy = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            self.source_stack.widget(i).setSizePolicy(policy, policy)
        self.source_stack.adjustSize()

    def _mode_changed(self) -> None:
        folder = self.mode_folder.isChecked()
        self.path_edit.setPlaceholderText(
            "scegli la cartella del tuo progetto" if folder else "scegli il file del tuo codice"
        )
        self.path_edit.clear()
        self.source_summary.setText("")

    def _pick_source(self) -> None:
        if self.mode_folder.isChecked():
            path = QFileDialog.getExistingDirectory(self, "Cartella del tuo progetto")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Il file del tuo codice")
        if path:
            self.path_edit.setText(path)
            self._summarize()

    def _summarize(self) -> None:
        """Dice subito quanti file e pezzi verranno tradotti."""
        from drdeconstruct.core.errors import DrDeconstructError
        from drdeconstruct.software.port_source import load_sources

        text = self.path_edit.text().strip()
        if not text:
            return
        path = Path(text).expanduser()
        self._set_source_name(path.stem or "porting")
        try:
            files = load_sources(path)
        except (DrDeconstructError, OSError) as exc:
            self.source_summary.setText(str(exc))
            return
        langs = sorted({SOURCE_LANGUAGE_LABELS.get(f.language, f.language) for f in files})
        units = sum(len(f.units) for f in files)
        self.source_summary.setText(
            f"Trovati {len(files)} file ({', '.join(langs)}): "
            f"{_count(units, 'pezzo', 'pezzi')} da tradurre."
        )

    def _set_source_name(self, stem: str) -> None:
        self._source_name = stem
        self.folder_edit.setText(str(default_folder(stem)))

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Cartella (vuota) per il porting")
        if folder:
            self.folder_edit.setText(folder)

    def _open_folder(self) -> None:
        if self.result_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_dir)))

    def stop(self) -> None:
        self._stop_requested = True
        self.stop_btn.setEnabled(False)
        self._status("Mi fermo dopo il pezzo in corso e salvo ciò che è pronto…")

    def start(self) -> None:
        from drdeconstruct import cli
        from drdeconstruct.software.port import run_port
        from drdeconstruct.software.port_source import from_text, guess_language, load_sources

        if self._task and self._task.isRunning():
            return
        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            self.banner.warning("Manca la cartella: indica dove salvare il porting (passo 3).")
            return
        folder = Path(folder_text).expanduser()
        if folder.exists() and any(folder.iterdir()):
            self.banner.warning(
                "La cartella scelta contiene già dei file. Scegline una vuota o nuova "
                "per non sovrascrivere nulla (passo 3)."
            )
            return

        pasted = self.mode_text.isChecked()
        path = self.path_edit.text().strip()
        code = self.code_input.toPlainText()
        if pasted and not code.strip():
            self.banner.warning("Manca il codice: incollalo nel passo 1.")
            return
        if not pasted and not path:
            self.banner.warning("Manca il codice: premi «Scegli…» nel passo 1.")
            return

        settings = self._settings()
        target = self.lang_box.currentData()
        check = self.check_box.isChecked()
        name = self._source_name
        source_lang = self.source_lang_box.currentData() or (guess_language(code) if pasted else "")

        def job(report):
            if pasted:
                files = from_text(code, source_lang, name)
            else:
                files = load_sources(Path(path).expanduser())
            report(("units", [f"{f.path}: {u.name}" for f in files for u in f.units]))
            return run_port(
                cli.make_backend(settings),
                files,
                folder,
                target,
                name=name,
                check=check,
                progress=lambda i, n, label: report(("start", i, n, label)),
                on_update=lambda project: report(("project", project)),
                should_stop=lambda: self._stop_requested,
                stage=lambda text: report(("stage", text)),
            )

        self._stop_requested = False
        self.result_dir = None
        self.open_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.unit_list.clear()
        self.preview.clear()
        self.checklist.clear()
        self._items = {}
        self.progress.setRange(0, 0)
        self.banner.busy("Traduzione in corso: segui l'anteprima a destra.")
        self._status("Preparo il lavoro…")

        self._task = Task(job, self, with_report=True)
        self._task.progress.connect(self._on_progress)
        self._task.done.connect(self._on_done)
        self._task.failed.connect(self._on_failed)
        self._task.start()

    # --- Aggiornamenti dal thread di lavoro -------------------------------
    def _on_progress(self, msg: tuple) -> None:
        from drdeconstruct.software.port import preview, render_checklist

        kind = msg[0]
        if kind == "stage":
            self.progress.setRange(0, 0)
            self._status(msg[1])
        elif kind == "units":
            labels = msg[1]
            self._items = {label: i for i, label in enumerate(labels)}
            self.unit_list.addItems([f"○ {label}" for label in labels])
            self.progress.setRange(0, len(labels))
            self.progress.setValue(0)
        elif kind == "start":
            _, i, n, label = msg
            self._status(f"Pezzo {i} di {n}: il modello sta traducendo {label}…")
            self._mark(label, f"✱ {label} (in corso)")
        elif kind == "project":
            project = msg[1]
            count = 0
            for pf in project.files:
                for origin, unit in zip(pf.origins, pf.units, strict=True):
                    self._mark(
                        f"{pf.source}: {origin.name}", f"✓ {pf.source}: {origin.name} → {unit.name}"
                    )
                    count += 1
                for name in pf.failed:
                    self._mark(f"{pf.source}: {name}", f"✗ {pf.source}: {name} (non riuscito)")
                    count += 1
            if self.progress.maximum() > 0:
                self.progress.setValue(min(count, self.progress.maximum()))
            self.preview.setPlainText(preview(project))
            self.preview.moveCursor(QTextCursor.MoveOperation.End)
            self.checklist.setMarkdown(render_checklist(project))

    def _mark(self, label: str, text: str) -> None:
        index = self._items.get(label)
        if index is not None:
            self.unit_list.item(index).setText(text)
            self.unit_list.scrollToItem(self.unit_list.item(index))

    def _on_done(self, result) -> None:
        from drdeconstruct.software.port import preview, render_checklist

        project, paths = result
        self.result_dir = Path(self.folder_edit.text().strip()).expanduser()
        self._reset_buttons()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.preview.setPlainText(preview(project))
        self.checklist.setMarkdown(render_checklist(project))
        units = sum(len(pf.units) for pf in project.files)
        failed = sum(len(pf.failed) for pf in project.files)
        if project.compiler is None:
            compiled = "compilazione non controllata"
        elif project.compile_ok:
            compiled = "compila senza errori"
        else:
            compiled = f"restano {len(project.compile_issues)} errori di compilazione"
        stopped = " (interrotto)" if self._stop_requested else ""
        failed_text = f", {failed} non riusciti" if failed else ""
        done = _count(units, "pezzo tradotto", "pezzi tradotti")
        summary = f"Fatto{stopped}: {done}{failed_text}, {compiled}."
        self._status(f"{summary} Salvato in {self.result_dir}")
        self.open_btn.setEnabled(True)
        self.tabs.setCurrentWidget(self.checklist)
        message = f"{summary} Leggi la checklist (anche in CHECKLIST.md) prima di usare il codice."
        if project.compile_ok:
            self.banner.success(message)
        else:
            self.banner.warning(message)

    def _on_failed(self, message: str) -> None:
        self._reset_buttons()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._status("Non è andata a buon fine.")
        self.banner.error(f"Porting non riuscito. {message}")

    def _reset_buttons(self) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _status(self, text: str) -> None:
        self.status_label.setText(text)
        if self._status_bar is not None:
            self._status_bar.showMessage(text)


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label
