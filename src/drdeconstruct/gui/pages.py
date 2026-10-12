"""Schede guidate: spiega codice o dati, decompila, sito web, dispositivi,
verifica qualità.

Ogni scheda è una `Page` con passaggi numerati. I lavori lenti passano da
`self.run(...)`, che la finestra principale esegue in un thread separato
mostrando l'avanzamento nel riquadro in alto della pagina.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QTextBrowser,
    QWidget,
)

from drdeconstruct.config import Settings
from drdeconstruct.core.errors import BackendError
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind
from drdeconstruct.gui.components import Page, Runner, button, label, row

SettingsFn = Callable[[], Settings]

KIND_LABELS = {
    ArtifactKind.PSEUDOCODE_C: "Codice C decompilato (da Ghidra o IDA)",
    ArtifactKind.ASSEMBLY: "Assembly (istruzioni del processore)",
    ArtifactKind.FLASH_DUMP: "Dump di una memoria flash o ROM (esadecimale)",
    ArtifactKind.REGISTER_MAP: "Registri di un microcontrollore",
    ArtifactKind.BUS_LOG: "Log di un bus seriale (UART, SPI, I2C, CAN)",
    ArtifactKind.WEB_PAGE: "Pagina web salvata (HTML)",
}

# Esempi minimi per provare subito ogni tipo di analisi.
SAMPLES = {
    ArtifactKind.PSEUDOCODE_C: (
        "uint FUN_00401a20(byte *param_1, int param_2)\n{\n  uint uVar1;\n  int i;\n\n"
        "  uVar1 = 0xffffffff;\n  while (param_2 != 0) {\n    uVar1 = uVar1 ^ *param_1;\n"
        "    for (i = 0; i < 8; i++) {\n      if ((uVar1 & 1) == 0) uVar1 = uVar1 >> 1;\n"
        "      else uVar1 = uVar1 >> 1 ^ 0xedb88320;\n    }\n    param_1++;\n"
        "    param_2--;\n  }\n  return ~uVar1;\n}\n"
    ),
    ArtifactKind.ASSEMBLY: (
        "sub_401000:\n  push ebp\n  mov ebp, esp\n  mov ecx, [ebp+8]\n  xor eax, eax\n"
        "loop:\n  cmp byte [ecx+eax], 0\n  je done\n  inc eax\n  jmp loop\n"
        "done:\n  pop ebp\n  ret\n"
    ),
    ArtifactKind.FLASH_DUMP: (
        "00000000  27 05 19 56 a1 b2 c3 d4  5f 3a 1c 20 00 1d 4e 20  |'..V...._:. ..N |\n"
        "00000010  80 00 00 00 80 00 00 00  6e 8f 2a 11 05 05 02 00  |........n.*.....|\n"
        "00000020  4c 69 6e 75 78 2d 33 2e  31 30 2e 31 34 00 00 00  |Linux-3.10.14...|\n"
    ),
    ArtifactKind.REGISTER_MAP: (
        "0x40011000 GPIOC_CRL  = 0x44444444\n0x40011004 GPIOC_CRH  = 0x44344444\n"
        "0x40021018 RCC_APB2ENR = 0x00000014\n0x4001100C GPIOC_ODR  = 0x00002000\n"
    ),
    ArtifactKind.BUS_LOG: (
        "U-Boot 2016.07 (Mar 10 2021 - 10:12:41)\nDRAM:  64 MiB\n"
        "SF: Detected XM25QH128A with page size 256 Bytes, erase size 64 KiB, total 16 MiB\n"
        "Hit any key to stop autoboot:  0\nStarting kernel ...\n"
    ),
    ArtifactKind.WEB_PAGE: (
        "<!doctype html><html><head><title>Esempio</title></head><body>\n"
        "<header><nav><a href='/'>Home</a><a href='/prodotti'>Prodotti</a></nav></header>\n"
        "<main><section class='hero'><h1>Titolo</h1><a class='btn'>Scopri</a></section>\n"
        "</main></body></html>\n"
    ),
}

# Processori comuni per i firmware grezzi (stringhe "lingua" di Ghidra).
PROCESSORS = [
    ("", "Automatico (per .exe, .elf, .dll e simili)"),
    ("ARM:LE:32:Cortex", "ARM Cortex-M (STM32, nRF, ESP32-C3…)"),
    ("ARM:LE:32:v7", "ARM 32 bit (telecamere, router)"),
    ("AARCH64:LE:64:v8A", "ARM 64 bit"),
    ("MIPS:LE:32:default", "MIPS little-endian (molte telecamere IP)"),
    ("MIPS:BE:32:default", "MIPS big-endian (router)"),
    ("x86:LE:32:default", "x86 32 bit"),
    ("x86:LE:64:default", "x86 64 bit"),
    ("8051:BE:16:default", "8051 (microcontrollori economici)"),
]

FLASH_PROGRAMMERS = [
    ("ch341a_spi", "CH341A (il più diffuso ed economico)"),
    ("ft2232_spi:type=2232H", "FT2232H"),
    ("serprog:dev=COM3", "serprog (Arduino/Raspberry Pi Pico): cambia COM3 con la tua porta"),
    ("linux_spi:dev=/dev/spidev0.0", "Raspberry Pi (SPI)"),
]


def _save_text(parent: QWidget, title: str, default: str, filters: str, text: str) -> Path | None:
    path, _ = QFileDialog.getSaveFileName(parent, title, default, filters)
    if not path:
        return None
    Path(path).write_text(text, encoding="utf-8")
    return Path(path)


def open_folder(folder: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


# --- Spiega codice o dati -------------------------------------------------
class AnalysisPage(Page):
    nav_title = "Spiega codice o dati"
    nav_icon = "code"

    def __init__(self, run: Runner | None, settings: SettingsFn, parent=None):
        super().__init__(
            "Spiega codice o dati",
            "Incolla codice decompilato, assembly, un dump o un log: l'IA ti spiega cosa fa, "
            "con nomi chiari e passo per passo.",
            self.nav_icon,
            run,
            parent=parent,
        )
        self._settings = settings
        self._result: dict | None = None

        s1 = self.step(1, "Che cosa vuoi far spiegare?")
        self.kind_box = QComboBox()
        for kind, text in KIND_LABELS.items():
            self.kind_box.addItem(text, kind.value)
        s1.add(self.kind_box)
        self.arch_edit = QLineEdit()
        self.arch_edit.setPlaceholderText("Processore, se lo sai (es. mips32el, arm). Facoltativo.")
        self.context_edit = QLineEdit()
        self.context_edit.setPlaceholderText(
            "Cosa sai già? Es. «firmware della mia telecamera, cerco il protocollo». Facoltativo."
        )
        s1.add(self.arch_edit).add(self.context_edit)

        s2 = self.step(
            2,
            "Incolla il contenuto o apri un file",
            "Non hai niente sotto mano? Premi «Prova con un esempio».",
        )
        self.input_edit = QPlainTextEdit()
        self.input_edit.setObjectName("code")
        self.input_edit.setMinimumHeight(170)
        self.input_edit.setPlaceholderText("Incolla qui pseudocodice, assembly, log o dump…")
        s2.add(self.input_edit)
        s2.add(
            row(
                button("Apri file…", self._load_file, icon_name="folder"),
                button("Prova con un esempio", self._load_sample, icon_name="help"),
                None,
            )
        )

        s3 = self.step(
            3,
            "Avvia l'analisi",
            "Usa il motore IA scelto in alto. Più funzioni C incollate insieme vengono "
            "spiegate una alla volta, con nomi coerenti tra loro.",
        )
        self.run_btn = button("Spiega", self._run_analysis, "primary", "play")
        s3.add(row(self.run_btn, None))
        self.busy_widgets = [self.run_btn]

        s4 = self.step(4, "Leggi il risultato")
        self.output_view = QTextBrowser()
        self.output_view.setOpenExternalLinks(True)
        self.output_view.setMinimumHeight(260)
        self.output_view.setPlaceholderText("Qui compare la spiegazione.")
        self.save_md_btn = button("Salva come testo…", self._save_md, icon_name="save")
        self.save_json_btn = button("Salva dati (JSON)…", self._save_json, icon_name="save")
        self.copy_btn = button("Copia", self._copy)
        for b in (self.save_md_btn, self.save_json_btn, self.copy_btn):
            b.setEnabled(False)
        s4.add(self.output_view)
        s4.add(row(self.save_md_btn, self.save_json_btn, self.copy_btn, None))

    def kind(self) -> ArtifactKind:
        return ArtifactKind(self.kind_box.currentData())

    def set_input(self, kind: ArtifactKind, content: str) -> None:
        """Usato dalle altre schede, es. per spiegare un log seriale appena catturato."""
        self.kind_box.setCurrentIndex(self.kind_box.findData(kind.value))
        self.input_edit.setPlainText(content)
        self.banner.info("Contenuto pronto. Premi «Spiega» per avviare l'analisi.")

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Apri file")
        if path:
            self.input_edit.setPlainText(Path(path).read_text(encoding="utf-8", errors="replace"))

    def _load_sample(self) -> None:
        self.input_edit.setPlainText(SAMPLES[self.kind()])
        self.banner.info("Esempio caricato. Premi «Spiega» per vedere come funziona.")

    def _run_analysis(self) -> None:
        from drdeconstruct.cli import analyze_functions, build_engine
        from drdeconstruct.preprocess.chunker import split_c_functions

        content = self.input_edit.toPlainText().strip()
        if not content:
            self.banner.warning(
                "Manca il contenuto: incollalo nel passo 2, apri un file o premi "
                "«Prova con un esempio»."
            )
            return
        settings = self._settings()
        kind = self.kind()
        req = AnalysisRequest(
            content=content,
            domain=kind.domain,
            kind=kind,
            arch=self.arch_edit.text().strip() or None,
            context=self.context_edit.text().strip(),
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
            else "Analisi in corso: di solito bastano dai 20 secondi a un paio di minuti…"
        )
        self.run(job, on_done=self.show_result, busy=busy)

    def show_result(self, result: dict) -> None:
        from drdeconstruct.report import to_markdown

        self._result = result
        self.output_view.setMarkdown(to_markdown(result))
        for b in (self.save_md_btn, self.save_json_btn, self.copy_btn):
            b.setEnabled(True)
        self.banner.success("Analisi completata. Puoi salvarla o copiarla con i pulsanti sotto.")

    def _save_md(self) -> None:
        from drdeconstruct.report import to_markdown

        if self._result is not None:
            path = _save_text(
                self,
                "Salva spiegazione",
                "spiegazione.md",
                "Testo (*.md *.txt)",
                to_markdown(self._result),
            )
            if path:
                self.banner.success(f"Salvato in {path}")

    def _save_json(self) -> None:
        if self._result is not None:
            text = json.dumps(self._result, indent=2, ensure_ascii=False)
            path = _save_text(self, "Salva dati", "analisi.json", "JSON (*.json)", text)
            if path:
                self.banner.success(f"Salvato in {path}")

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.output_view.toPlainText())
        self.banner.success("Testo copiato negli appunti.")


# --- Decompila un programma ----------------------------------------------
class DecompilePage(Page):
    nav_title = "Decompila un programma"
    nav_icon = "chip"
    ghidra_changed = Signal(str)
    open_scaffold = Signal()

    def __init__(self, run: Runner | None, settings: SettingsFn, parent=None):
        super().__init__(
            "Decompila un programma",
            "Apri un .exe o un firmware: Ghidra lo trasforma in codice C leggibile e, se vuoi, "
            "l'IA spiega ogni funzione.",
            self.nav_icon,
            run,
            parent=parent,
        )
        self._settings = settings
        self._output = ""

        s1 = self.step(
            1,
            "Prepara Ghidra (solo la prima volta)",
            "Ghidra è il decompilatore gratuito della NSA. Scaricalo, estrai lo zip in una "
            "cartella e indicala qui sotto. Serve anche Java 21.",
        )
        self.ghidra_status = label("", "hint")
        s1.add(self.ghidra_status)
        s1.add(
            row(
                button("Indica la cartella di Ghidra…", self._pick_ghidra, icon_name="folder"),
                button("Scarica Ghidra", lambda: self._open_link("ghidra"), "link"),
                button("Scarica Java 21", lambda: self._open_link("java"), "link"),
                None,
            )
        )

        s2 = self.step(
            2,
            "Scegli il file da decompilare",
            "Un programma (.exe, .dll, .elf) o un "
            "firmware (.bin) che ti appartiene o è open source.",
        )
        self.binary_edit = QLineEdit()
        self.binary_edit.setPlaceholderText("Percorso del file")
        s2.add(row(self.binary_edit, button("Scegli file…", self._pick_binary, icon_name="folder")))

        s3 = self.step(
            3,
            "Che processore usa?",
            "Per .exe ed .elf lascia «Automatico». Per un firmware grezzo scegli il processore "
            "(lo trovi stampato sul chip o nella scheda tecnica); puoi anche scriverlo a mano.",
        )
        self.proc_box = QComboBox()
        self.proc_box.setEditable(True)
        for value, text in PROCESSORS:
            self.proc_box.addItem(f"{text}" if not value else f"{value}  —  {text}", value)
        s3.add(self.proc_box)

        s4 = self.step(4, "Cosa vuoi ottenere?")
        self.only_decompile = QRadioButton("Solo il codice C (veloce e gratis, senza IA)")
        self.with_ai = QRadioButton("Il codice e una spiegazione di ogni funzione con l'IA")
        self.only_decompile.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.only_decompile)
        group.addButton(self.with_ai)
        s4.add(self.only_decompile).add(self.with_ai)
        s4.add(
            row(
                label("Vuoi un codice riscritto da completare?", "hint", wrap=False),
                button("Usa «Scheletro di codice»", self.open_scaffold.emit, "link"),
                None,
            )
        )

        s5 = self.step(5, "Avvia", "Ghidra può impiegare da pochi secondi a vari minuti.")
        self.decompile_btn = button("Decompila", self._run_decompile, "primary", "play")
        s5.add(row(self.decompile_btn, None))
        self.busy_widgets = [self.decompile_btn]

        s6 = self.step(6, "Risultato")
        self.decompile_view = QTextBrowser()
        self.decompile_view.setObjectName("code")
        self.decompile_view.setMinimumHeight(260)
        self.decompile_view.setPlaceholderText("Qui compare il codice decompilato.")
        self.save_btn = button("Salva…", self._save, icon_name="save")
        self.save_btn.setEnabled(False)
        s6.add(self.decompile_view).add(row(self.save_btn, None))
        self.refresh_ghidra()

    def refresh_ghidra(self) -> None:
        from drdeconstruct.doctor import check_ghidra

        check = check_ghidra()
        mark = "✓" if check.ok else "✗"
        self.ghidra_status.setText(f"{mark} {check.detail}" + ("" if check.ok else f" {check.fix}"))

    def _open_link(self, which: str) -> None:
        from drdeconstruct.doctor import GHIDRA_DOWNLOAD, JAVA_DOWNLOAD

        url = GHIDRA_DOWNLOAD if which == "ghidra" else JAVA_DOWNLOAD
        QDesktopServices.openUrl(QUrl(url))

    def _pick_ghidra(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Cartella di Ghidra (quella che contiene «support» e «ghidraRun»)"
        )
        if folder:
            self.set_ghidra_folder(folder)

    def set_ghidra_folder(self, folder: str) -> None:
        os.environ["GHIDRA_INSTALL_DIR"] = folder
        self.refresh_ghidra()
        self.ghidra_changed.emit(folder)

    def _pick_binary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Scegli il programma o il firmware")
        if path:
            self.binary_edit.setText(path)

    def processor(self) -> str | None:
        index = self.proc_box.currentIndex()
        text = self.proc_box.currentText().strip()
        if index >= 0 and self.proc_box.itemText(index) == text:
            return self.proc_box.itemData(index) or None
        return text.split()[0] if text else None  # scritto a mano

    def _run_decompile(self) -> None:
        from drdeconstruct.preprocess.ghidra import GhidraExporter

        path = self.binary_edit.text().strip()
        if not path:
            self.banner.warning("Manca il file: premi «Scegli file…» nel passo 2.")
            return
        settings = self._settings()
        processor = self.processor()
        analyze = self.with_ai.isChecked()

        def job():
            program = GhidraExporter().export(path, processor=processor)
            if not analyze:
                return ("code", program.as_c_source())
            from drdeconstruct.cli import analyze_functions, build_engine

            base = AnalysisRequest(content="", kind=ArtifactKind.PSEUDOCODE_C, arch=program.arch)
            funcs = [(f"{f.name}@{f.entry}", f.code) for f in program.functions]
            llm, orch = build_engine(settings)
            return ("analysis", analyze_functions(orch, base, funcs, llm=llm))

        self.run(job, on_done=self.show_result, busy="Ghidra sta decompilando il file…")

    def show_result(self, result) -> None:
        from drdeconstruct.report import to_markdown

        kind, payload = result
        if kind == "code":
            self._output = payload
            self.decompile_view.setPlainText(payload)
        else:
            self._output = json.dumps(payload, indent=2, ensure_ascii=False)
            self.decompile_view.setMarkdown(to_markdown(payload))
        self.save_btn.setEnabled(True)
        self.banner.success("Fatto. Salva il risultato con «Salva…».")

    def _save(self) -> None:
        default = "decompilato.c" if not self.with_ai.isChecked() else "analisi.json"
        path = _save_text(self, "Salva risultato", default, "Tutti i file (*)", self._output)
        if path:
            self.banner.success(f"Salvato in {path}")


# --- Sito web --------------------------------------------------------------
class WebPage(Page):
    nav_title = "Studia un sito web"
    nav_icon = "globe"

    def __init__(self, run: Runner | None, settings: SettingsFn, parent=None):
        super().__init__(
            "Studia un sito web",
            "Capisci come è fatta una pagina, salvane una copia privata per studiarla e "
            "ottieni uno scheletro pulito per costruire la tua versione.",
            self.nav_icon,
            run,
            parent=parent,
        )
        self._settings = settings
        self._web_result = None
        self._last_folder: Path | None = None

        s1 = self.step(1, "Scrivi l'indirizzo della pagina")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Es. www.esempio.it")
        self.url_edit.returnPressed.connect(self._run_web)
        s1.add(self.url_edit)

        s2 = self.step(
            2,
            "Scegli cosa fare",
            "«Analizza» spiega sezioni, componenti, stile e tecnologie. «Salva copia sul PC» "
            "scarica questa sola pagina con immagini e stili, da aprire anche senza internet.",
        )
        self.web_struct_only = QCheckBox("Solo struttura, senza IA (veloce e gratis)")
        self.web_btn = button("Analizza", self._run_web, "primary", "search")
        self.mirror_btn = button("Salva copia sul PC…", self._run_mirror, icon_name="save")
        s2.add(self.web_struct_only).add(row(self.web_btn, self.mirror_btn, None))
        self.busy_widgets = [self.web_btn, self.mirror_btn]

        s3 = self.step(3, "Leggi la spiegazione")
        self.web_view = QTextBrowser()
        self.web_view.setMinimumHeight(260)
        self.web_view.setPlaceholderText("Qui compare la spiegazione della pagina.")
        s3.add(self.web_view)

        s4 = self.step(
            4,
            "Costruisci la tua versione",
            "Lo scheletro contiene index.html, styles.css, script.js e NOTE.md con testi "
            "segnaposto da sostituire con i tuoi. Richiede l'analisi con l'IA.",
        )
        self.scaffold_btn = button("Salva scheletro…", self._save_scaffold, icon_name="layers")
        self.save_json_btn = button("Salva analisi (JSON)…", self._save_web_json, icon_name="save")
        self.open_folder_btn = button("Apri cartella", self._open_last_folder, icon_name="folder")
        for b in (self.scaffold_btn, self.save_json_btn, self.open_folder_btn):
            b.setEnabled(False)
        s4.add(row(self.scaffold_btn, self.save_json_btn, None, self.open_folder_btn))

        self.body.addWidget(
            label(
                "Si scaricano solo file pubblici, rispettando robots.txt; login e paywall non "
                "vengono aggirati. La copia è privata, per studio: non ripubblicarla. Per un "
                "sito tuo usa lo scheletro con contenuti tuoi.",
                "hint",
            )
        )

    def _web_url(self) -> str | None:
        url = self.url_edit.text().strip()
        if not url:
            self.banner.warning("Manca l'indirizzo: scrivilo nel passo 1, es. www.esempio.it")
            return None
        return url if "://" in url else "https://" + url

    def _run_web(self) -> None:
        from drdeconstruct.cli import run_web

        url = self._web_url()
        if not url:
            return
        settings = None if self.web_struct_only.isChecked() else self._settings()

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
        self.run(job, on_done=self.show_web, busy=busy)

    def show_web(self, result) -> None:
        from drdeconstruct.web.scaffold import render_report

        snapshot, analysis = result
        self._web_result = result
        self.web_view.setMarkdown(render_report(snapshot, analysis))
        self.scaffold_btn.setEnabled(analysis is not None)
        self.save_json_btn.setEnabled(True)
        self.banner.success(
            "Analisi pronta. Ora puoi salvare lo scheletro della tua versione (passo 4)."
            if analysis is not None
            else "Struttura pronta. Per lo scheletro togli la spunta «Solo struttura» e rianalizza."
        )

    def _save_web_json(self) -> None:
        if not self._web_result:
            return
        snapshot, analysis = self._web_result
        payload = {"snapshot": snapshot.model_dump()}
        if analysis is not None:
            payload["analysis"] = analysis.model_dump()
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        path = _save_text(self, "Salva analisi", "analisi.json", "JSON (*.json)", text)
        if path:
            self.banner.success(f"Analisi salvata in {path}")

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
            self.banner.error(f"Non salvato: {exc}")
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

        self.run(
            lambda progress: mirror_page(url, target, progress=progress),
            on_done=done,
            busy="Salvo la pagina…",
            with_progress=True,
        )

    def _done_in_folder(self, folder: Path, message: str) -> None:
        self._last_folder = folder
        self.open_folder_btn.setEnabled(True)
        self.banner.success(message)

    def _open_last_folder(self) -> None:
        if self._last_folder:
            open_folder(self._last_folder)


# --- Dispositivi collegati -------------------------------------------------
class DevicesPage(Page):
    nav_title = "Dispositivi collegati"
    nav_icon = "usb"
    explain = Signal(str, str)  # tipo, contenuto: da spiegare nella scheda di analisi
    open_binary = Signal(str)

    def __init__(self, run: Runner | None, settings: SettingsFn, parent=None):
        super().__init__(
            "Dispositivi collegati",
            "Trova adattatori USB, porte seriali e dispositivi Bluetooth; cattura il log di "
            "avvio di una scheda o fai il backup della sua memoria flash.",
            self.nav_icon,
            run,
            parent=parent,
        )
        self._settings = settings
        self._log = ""

        s1 = self.step(
            1,
            "Collega l'adattatore",
            "Per la console seriale serve un adattatore USB-UART (CH340, CP2102, FTDI) collegato "
            "ai pin TX, RX e GND della scheda. Per la memoria flash serve un programmatore "
            "(es. CH341A) e il programma flashrom.",
        )
        s1.add(
            row(
                button("Scansiona USB", self._scan_usb, icon_name="usb"),
                button("Porte seriali", self._scan_serial, icon_name="refresh"),
                button("Scansiona Bluetooth", self._scan_ble, icon_name="search"),
                None,
            )
        )
        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(130)
        s1.add(self.device_list)

        s2 = self.step(
            2,
            "Cattura il log di avvio (console seriale)",
            "Scegli la porta, premi «Cattura» e accendi la scheda subito dopo. La velocità "
            "più comune è 115200.",
        )
        self.port_box = QComboBox()
        self.port_box.setEditable(True)
        self.port_box.setPlaceholderText("Porta, es. COM3 o /dev/ttyUSB0")
        self.baud_box = QComboBox()
        for baud in ("115200", "57600", "38400", "19200", "9600", "921600"):
            self.baud_box.addItem(baud)
        self.seconds_box = QSpinBox()
        self.seconds_box.setRange(3, 120)
        self.seconds_box.setValue(15)
        self.seconds_box.setSuffix(" s")
        self.capture_btn = button("Cattura", self._capture, "primary", "play")
        s2.add(row(self.port_box, self.baud_box, self.seconds_box, self.capture_btn))
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("code")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(140)
        self.log_view.setPlaceholderText("Qui compare il testo ricevuto dalla scheda.")
        self.explain_btn = button("Fai spiegare all'IA", self._explain_log, icon_name="code")
        self.save_log_btn = button("Salva log…", self._save_log, icon_name="save")
        self.explain_btn.setEnabled(False)
        self.save_log_btn.setEnabled(False)
        s2.add(self.log_view).add(row(self.explain_btn, self.save_log_btn, None))

        s3 = self.step(
            3,
            "Backup della memoria flash (sola lettura)",
            "Legge tutto il chip e lo salva in un file: è il tuo punto di ripristino. Da qui "
            "non si scrive mai sul chip.",
        )
        self.programmer_box = QComboBox()
        self.programmer_box.setEditable(True)
        for value, text in FLASH_PROGRAMMERS:
            self.programmer_box.addItem(f"{value}  —  {text}", value)
        self.backup_btn = button("Leggi e salva…", self._backup, "primary", "save")
        s3.add(row(self.programmer_box, self.backup_btn))
        self._backup_path: Path | None = None
        self.decompile_backup_btn = button(
            "Apri il backup nel decompilatore", self._open_backup, "link"
        )
        self.decompile_backup_btn.setEnabled(False)
        s3.add(row(self.decompile_backup_btn, None))
        self.busy_widgets = [self.capture_btn, self.backup_btn]

    def _scan_usb(self) -> None:
        from drdeconstruct.acquisition.usb import list_usb_devices

        self._list_devices(list_usb_devices, "Scansione USB…")

    def _scan_serial(self) -> None:
        from drdeconstruct.acquisition.usb import list_serial_ports

        self._list_devices(list_serial_ports, "Lettura delle porte seriali…")

    def _scan_ble(self) -> None:
        from drdeconstruct.acquisition.bluetooth import scan_ble

        self._list_devices(scan_ble, "Scansione Bluetooth (circa 8 secondi)…")

    def _list_devices(self, fn, busy: str) -> None:
        self.device_list.clear()
        self.run(fn, on_done=self.show_devices, busy=busy)

    def show_devices(self, devices) -> None:
        from drdeconstruct.acquisition.models import LinkKind

        self.device_list.addItems([str(d) for d in devices] or ["(nessun dispositivo trovato)"])
        ports = [d.identifier for d in devices if d.kind is LinkKind.SERIAL]
        for port in ports:
            if self.port_box.findText(port) < 0:
                self.port_box.addItem(port)
        if ports:
            self.port_box.setCurrentText(ports[0])
            self.banner.info(f"Trovate {len(ports)} porte seriali: ora puoi catturare il log.")
        elif devices:
            self.banner.success(f"Trovati {len(devices)} dispositivi.")
        else:
            self.banner.warning("Nessun dispositivo trovato. Controlla il cavo e riprova.")

    def _capture(self) -> None:
        from drdeconstruct.acquisition.usb import SerialConsole

        port = self.port_box.currentText().strip()
        if not port:
            self.banner.warning("Indica la porta: premi «Porte seriali» nel passo 1 o scrivila.")
            return
        baud = int(self.baud_box.currentText())
        seconds = self.seconds_box.value()
        self.run(
            lambda: SerialConsole(port, baud).capture(seconds),
            on_done=self.show_log,
            busy=f"Ascolto {port} per {seconds} secondi: accendi la scheda adesso…",
        )

    def show_log(self, text: str) -> None:
        self._log = text
        self.log_view.setPlainText(text or "(nessun dato ricevuto)")
        has = bool(text.strip())
        self.explain_btn.setEnabled(has)
        self.save_log_btn.setEnabled(has)
        if has:
            self.banner.success("Log catturato. Premi «Fai spiegare all'IA» per capirlo.")
        else:
            self.banner.warning(
                "Nessun dato. Prova a scambiare i fili TX e RX o un'altra velocità."
            )

    def _explain_log(self) -> None:
        self.explain.emit(ArtifactKind.BUS_LOG.value, self._log)

    def _save_log(self) -> None:
        path = _save_text(self, "Salva log", "log_seriale.txt", "Testo (*.txt)", self._log)
        if path:
            self.banner.success(f"Salvato in {path}")

    def _backup(self) -> None:
        from drdeconstruct.acquisition.flash import FlashTool

        index = self.programmer_box.currentIndex()
        text = self.programmer_box.currentText().strip()
        if index >= 0 and self.programmer_box.itemText(index) == text:
            programmer = self.programmer_box.itemData(index)
        else:
            programmer = text.split()[0] if text else ""
        if not programmer:
            self.banner.warning("Scegli il programmatore.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Dove salvare il backup", "backup_flash.bin", "Immagine (*.bin)"
        )
        if not path:
            return
        target = Path(path)

        def done(image) -> None:
            self._backup_path = target
            self.decompile_backup_btn.setEnabled(True)
            self.banner.success(
                f"Backup salvato: {image.size:,} byte in {target}. Impronta SHA-256: "
                f"{image.sha256[:16]}… Conservalo in un posto sicuro."
            )

        self.run(
            lambda: FlashTool(programmer).backup(target),
            on_done=done,
            busy="Lettura del chip: può richiedere qualche minuto, non scollegare nulla…",
        )

    def _open_backup(self) -> None:
        if self._backup_path:
            self.open_binary.emit(str(self._backup_path))


# --- Verifica qualità ------------------------------------------------------
class QualityPage(Page):
    nav_title = "Verifica qualità"
    nav_icon = "gauge"

    def __init__(self, run: Runner | None, settings: SettingsFn, parent=None):
        super().__init__(
            "Verifica qualità",
            "Misura quanto il motore IA scelto è bravo a indovinare i nomi veri delle funzioni.",
            self.nav_icon,
            run,
            parent=parent,
        )
        self._settings = settings
        s1 = self.step(
            1,
            "Cosa fa questa verifica",
            "Fa analizzare alcune funzioni di esempio di cui conosciamo i nomi veri (CRC32, "
            "strlen, checksum, driver UART…) e conta quanti ne indovina. Usa il modello davvero: "
            "consuma un po' del tuo abbonamento e richiede qualche minuto.",
        )
        self.quality_global = QCheckBox("Nomi coerenti tra funzioni (consigliato)")
        self.quality_global.setChecked(True)
        s1.add(self.quality_global)

        s2 = self.step(2, "Avvia", "Usa il motore IA scelto in alto.")
        self.quality_btn = button("Avvia verifica", self._run_quality, "primary", "play")
        s2.add(row(self.quality_btn, None))
        self.busy_widgets = [self.quality_btn]

        s3 = self.step(3, "Risultato")
        self.quality_view = QPlainTextEdit()
        self.quality_view.setObjectName("code")
        self.quality_view.setReadOnly(True)
        self.quality_view.setMinimumHeight(220)
        self.quality_view.setPlaceholderText("Qui compare il punteggio per ogni caso.")
        s3.add(self.quality_view)

    def _run_quality(self) -> None:
        from drdeconstruct.cli import analyze_functions, build_engine
        from drdeconstruct.evaluation import load_cases, report, run_case

        settings = self._settings()
        use_global = self.quality_global.isChecked()

        def job():
            llm, orch = build_engine(settings)
            names_llm = llm if use_global else None
            results = [
                run_case(case, lambda req, fns: analyze_functions(orch, req, fns, llm=names_llm))
                for case in load_cases()
            ]
            return report(results)

        def done(text: str) -> None:
            self.quality_view.setPlainText(text)
            self.banner.success("Verifica completata.")

        self.run(job, on_done=done, busy="Verifica in corso: richiede qualche minuto…")
