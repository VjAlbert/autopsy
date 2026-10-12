"""Scheda "Scheletro di codice": passaggi guidati e anteprima dal vivo."""

import pytest

from tests.test_gui import _qt_or_skip
from tests.test_scaffold import CRC_SRC, SequenceLLM, skeleton_payloads


@pytest.fixture(scope="module")
def app():
    qapp = _qt_or_skip()
    return qapp.instance() or qapp([])


@pytest.fixture
def tab(app, monkeypatch):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.scaffold_tab import ScaffoldTab

    monkeypatch.setattr("drdeconstruct.gui.scaffold_tab.QMessageBox.warning", lambda *a: None)
    monkeypatch.setattr("drdeconstruct.gui.scaffold_tab.QMessageBox.critical", lambda *a: None)
    widget = ScaffoldTab(Settings(backend="ollama"))
    yield widget
    widget.close()


def _wait(app, tab):
    tab._task.wait(10000)
    app.processEvents()


def test_defaults_are_guided(tab):
    assert tab.mode_binary.isChecked() and tab.source_stack.currentIndex() == 0
    assert tab.lang_box.currentData() == "c"
    assert tab.backend_box.currentData() == "ollama"
    assert "DrDeconstruct" in tab.folder_edit.text()
    tab.mode_text.setChecked(True)
    assert tab.source_stack.currentIndex() == 1


def test_missing_input_starts_nothing(tab, tmp_path):
    tab.folder_edit.setText(str(tmp_path / "out"))
    tab.start()  # nessun binario scelto
    assert tab._task is None
    tab.mode_text.setChecked(True)
    tab.start()  # nessun codice incollato
    assert tab._task is None


def test_live_preview_grows_function_by_function(app, tab, tmp_path, monkeypatch):
    from drdeconstruct import cli

    llm = SequenceLLM(skeleton_payloads("python"))
    monkeypatch.setattr(cli, "make_backend", lambda s: llm)
    snapshots = []
    original = tab._on_progress

    def spy(msg):
        original(msg)
        if msg[0] == "module":
            snapshots.append(tab.preview.toPlainText())

    tab._on_progress = spy
    out = tmp_path / "out"
    tab.mode_text.setChecked(True)
    tab.code_input.setPlainText(CRC_SRC)
    tab.lang_box.setCurrentIndex(tab.lang_box.findData("python"))
    tab.folder_edit.setText(str(out))
    tab.start()
    _wait(app, tab)

    # l'anteprima si aggiorna dopo ogni funzione, non solo alla fine
    assert len(snapshots) == 2
    assert "def crc32_update" in snapshots[0] and "packet_checksum" not in snapshots[0]
    assert "def packet_checksum" in snapshots[1]
    assert tab.function_list.item(0).text().startswith("✓ FUN_00401a20 → crc32_update")
    assert (out / "scheletro.py").exists() and tab.open_btn.isEnabled()
    assert tab.run_btn.isEnabled() and not tab.stop_btn.isEnabled()


def test_stop_keeps_what_is_ready(app, tab, tmp_path, monkeypatch):
    from drdeconstruct import cli

    class StoppingLLM(SequenceLLM):
        def structured(self, system, user, schema):
            tab._stop_requested = True  # l'utente preme «Ferma» durante la prima funzione
            return super().structured(system, user, schema)

    llm = StoppingLLM(skeleton_payloads("c"))
    monkeypatch.setattr(cli, "make_backend", lambda s: llm)
    out = tmp_path / "out"
    tab.mode_text.setChecked(True)
    tab.code_input.setPlainText(CRC_SRC)
    tab.folder_edit.setText(str(out))
    tab.start()
    _wait(app, tab)
    assert len(llm.calls) == 1
    notes = (out / "NOTE.md").read_text(encoding="utf-8")
    assert "Interrotto" in notes and "crc32_update" in (out / "scheletro.c").read_text()
