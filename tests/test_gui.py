import pytest


def _qt_or_skip():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # librerie di sistema Qt assenti (es. CI minimale)
        pytest.skip(f"Qt non caricabile in questo ambiente: {exc}")
    return QApplication


@pytest.fixture(scope="module")
def app():
    qapp = _qt_or_skip()
    instance = qapp.instance() or qapp([])
    yield instance


def test_main_window_builds(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    assert win.windowTitle() == "DrDeconstruct"
    assert win.centralWidget().count() == 3
    assert win.backend_box.currentText() == "ollama"
    assert win.binary_edit.text() == ""
    win.close()


def test_scaffold_controls(app, tmp_path, monkeypatch):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    assert win.scaffold_lang.currentText() == "c"
    assert win.decompile_lang.count() == 3
    # Input non adatto: nessuna cartella chiesta, nessun lavoro avviato
    win.kind_box.setCurrentText("bus_log")
    win.input_edit.setPlainText("TX 0x55")
    monkeypatch.setattr("drdeconstruct.gui.main_window.QMessageBox.warning", lambda *a: None)
    win._scaffold_from_text()
    assert win._task is None
    win.close()


def test_scaffold_from_text_writes_files(app, tmp_path, monkeypatch):
    from drdeconstruct import cli
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow
    from tests.test_scaffold import CRC_SRC, SequenceLLM, skeleton_payloads

    monkeypatch.setattr(cli, "make_backend", lambda s: SequenceLLM(skeleton_payloads("python")))
    out = tmp_path / "skel"
    monkeypatch.setattr(
        "drdeconstruct.gui.main_window.QFileDialog.getExistingDirectory", lambda *a: str(out)
    )
    win = MainWindow(Settings(backend="ollama"))
    win.kind_box.setCurrentText("pseudocode_c")
    win.input_edit.setPlainText(CRC_SRC)
    win.scaffold_lang.setCurrentText("python")
    win._scaffold_from_text()
    win._task.wait(5000)
    app.processEvents()
    assert (out / "scheletro.py").exists()
    assert "crc32_update" in win.output_view.toPlainText()
    win.close()
