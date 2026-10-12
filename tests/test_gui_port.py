"""Scheda "Porta il tuo codice": passaggi guidati e anteprima dal vivo."""

import pytest

from tests.test_gui import _qt_or_skip
from tests.test_port import ADD_ALL_RS, MEAN_RS, STATS_PY, SequenceLLM, unit


@pytest.fixture(scope="module")
def app():
    qapp = _qt_or_skip()
    return qapp.instance() or qapp([])


@pytest.fixture
def tab(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.port_tab import PortTab

    widget = PortTab(Settings(backend="ollama"))
    yield widget
    widget.close()


def _wait(app, tab):
    tab._task.wait(10000)
    app.processEvents()


def test_defaults_are_guided(tab):
    assert tab.mode_file.isChecked() and tab.source_stack.currentIndex() == 0
    assert tab.lang_box.currentData() == "rust"
    assert tab.check_box.isChecked() and tab.checker_label.text()
    assert "DrDeconstruct" in tab.folder_edit.text()
    tab.mode_text.setChecked(True)
    assert tab.source_stack.currentIndex() == 1


def test_missing_input_starts_nothing(tab, tmp_path):
    tab.folder_edit.setText(str(tmp_path / "out"))
    tab.start()
    assert tab._task is None and "Scegli" in tab.banner.text
    tab.mode_text.setChecked(True)
    tab.start()
    assert tab._task is None and "incollalo" in tab.banner.text


def test_folder_summary(tab, tmp_path):
    (tmp_path / "a.py").write_text(STATS_PY)
    (tmp_path / "b.c").write_text("int f(void) { return 1; }\n")
    tab.mode_folder.setChecked(True)
    tab.path_edit.setText(str(tmp_path))
    tab._summarize()
    assert "Trovati 2 file" in tab.source_summary.text()
    assert "C" in tab.source_summary.text() and "Python" in tab.source_summary.text()


def test_pasted_code_is_translated_with_checklist(app, tab, tmp_path, monkeypatch):
    from drdeconstruct import cli

    llm = SequenceLLM([unit("codice", ADD_ALL_RS + "\n\n" + MEAN_RS)])
    monkeypatch.setattr(cli, "make_backend", lambda s: llm)
    out = tmp_path / "out"
    tab.mode_text.setChecked(True)
    tab.code_input.setPlainText(STATS_PY)
    tab.check_box.setChecked(False)
    tab.folder_edit.setText(str(out))
    tab.start()
    _wait(app, tab)

    assert "Linguaggio sorgente: Python" in llm.calls[0][1]  # riconosciuto da solo
    assert "pub fn add_all" in tab.preview.toPlainText()
    assert "Confronta con [1, 2, 3]" in tab.checklist.toPlainText()
    assert "1 pezzo tradotto" in tab.banner.text
    assert tab.unit_list.item(0).text().startswith("✓")
    assert (out / "Cargo.toml").exists() and (out / "CHECKLIST.md").exists()
    assert tab.open_btn.isEnabled() and tab.run_btn.isEnabled()
    assert "compilazione non controllata" in tab.banner.text
