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
    assert win.centralWidget().count() == 4
    assert win.backend_box.currentText() == "ollama"
    assert win.binary_edit.text() == ""
    win.close()


def test_gui_analyzes_several_functions_with_shared_names(app, monkeypatch):
    from drdeconstruct import cli
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow
    from tests.test_improvements import PROGRAM, SchemaLLM

    llm = SchemaLLM({"FUN_80001080": ("uart_putc", "high")})
    monkeypatch.setattr(cli, "make_backend", lambda settings: llm)
    win = MainWindow(Settings(backend="ollama"))
    win.kind_box.setCurrentText("pseudocode_c")
    win.input_edit.setPlainText(PROGRAM)
    win._run_analysis()
    win._task.wait(5000)
    app.processEvents()
    assert '"uart_putc"' in win.output_view.toPlainText()
    win.close()


def test_refusal_message_is_explained(app):
    from drdeconstruct.core.errors import RefusalError
    from drdeconstruct.gui.workers import Task

    messages = []

    def boom():
        raise RefusalError("cyber")

    task = Task(boom)
    task.failed.connect(messages.append)
    task.run()
    assert "modello di riserva" in messages[0] and "cyber" in messages[0]
