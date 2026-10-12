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
    assert win.tabs.count() == 4
    assert win.backend_box.currentData() == "ollama"
    assert win.binary_edit.text() == ""
    assert not win.scaffold_btn.isEnabled()
    assert win.mirror_btn.isEnabled()
    win.close()


def test_web_tab_shows_readable_report(app, monkeypatch, tmp_path):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow
    from drdeconstruct.web.extract import build_snapshot
    from drdeconstruct.web.schemas import WebAnalysis
    from tests.test_web import PAGE, WEB_PAYLOAD

    win = MainWindow(Settings(backend="ollama"))
    snap = build_snapshot("https://rossi.test/", PAGE)
    win._show_web((snap, WebAnalysis.model_validate(WEB_PAYLOAD)))
    text = win.web_view.toPlainText()
    assert "Griglia schede" in text and '"snapshot"' not in text
    assert win.scaffold_btn.isEnabled() and win.save_json_btn.isEnabled()

    win._show_web((snap, None))
    assert not win.scaffold_btn.isEnabled()
    win.close()
