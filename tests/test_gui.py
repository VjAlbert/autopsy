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


@pytest.fixture(autouse=True)
def _dispose_widgets(request):
    """Distrugge le finestre dei test nel thread principale.

    Le finestre restano vive in cicli di riferimenti (lambda collegate ai
    segnali); se il garbage collector le liberasse più tardi dentro il thread
    di lavoro di un altro test, Qt andrebbe in crash (segmentation fault).
    """
    yield
    if "app" not in request.fixturenames:
        return
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def test_main_window_builds(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    assert win.windowTitle() == "DrDeconstruct"
    assert win.tabs.count() == 7
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


def _tab(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.smarthome_tab import SmartHomeTab

    calls = []

    def run(fn, on_done, busy):
        calls.append(busy)
        on_done(fn())

    return SmartHomeTab(run, lambda: Settings(backend="ollama")), calls


def _inventory():
    from drdeconstruct.smarthome.inventory import Inventory
    from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice

    return Inventory(
        [
            SmartDevice(Ecosystem.XIAOMI, Channel.MIIO, "miio:1", address="10.0.0.5"),
            SmartDevice(Ecosystem.AQARA, Channel.BLE, "aa", name="lumi.sensor", address="AA:BB"),
            SmartDevice(Ecosystem.VALETUDO, Channel.MDNS, "v", name="robot", address="10.0.0.7"),
        ],
        {"ble": "No adapter"},
    )


def test_smarthome_tab_lists_and_describes(app):
    tab, _ = _tab(app)
    tab.set_inventory(_inventory())
    assert tab.device_list.count() == 3
    assert "✓ leggibile" in tab.device_list.item(0).text()
    assert "Bluetooth non disponibile" in tab.view.toPlainText()
    assert tab.guide_btn.isEnabled()
    tab.device_list.setCurrentRow(1)
    assert not tab.read_btn.isEnabled()
    assert "solo via Bluetooth" in tab.view.toPlainText()
    tab.device_list.setCurrentRow(0)
    assert tab.read_btn.isEnabled()


def test_smarthome_tab_reads_valetudo_without_password(app, monkeypatch):
    from drdeconstruct.smarthome import valetudo

    monkeypatch.setattr(valetudo, "read_robot", lambda ip: {"robot": {"modelName": "S5"}})
    tab, calls = _tab(app)
    tab.set_inventory(_inventory())
    tab.device_list.setCurrentRow(2)
    tab.read_state()
    assert calls == ["Lettura dello stato…"]
    assert "modelName: S5" in tab.view.toPlainText()


def test_smarthome_tab_cancelled_token_does_nothing(app):
    tab, calls = _tab(app)
    tab.ask_text = lambda *a, **k: None
    tab.set_inventory(_inventory())
    tab.device_list.setCurrentRow(0)
    tab.read_state()
    assert calls == []


def test_smarthome_tab_write_needs_confirmation(app):
    tab, calls = _tab(app)
    asked = []
    tab.confirm = lambda title, text: asked.append(title) or False
    tab.set_inventory(_inventory())
    tab.device_list.setCurrentRow(0)
    tab.method_edit.setText("app_start")
    tab.send_command()
    assert asked == ["Conferma il comando"]
    assert calls == []


def test_smarthome_tab_guide(app, monkeypatch):
    from drdeconstruct.llm import factory
    from tests.conftest import FakeLLM
    from tests.test_smarthome import GUIDE_PAYLOAD

    monkeypatch.setattr(factory, "make_backend", lambda settings: FakeLLM(GUIDE_PAYLOAD))
    tab, _ = _tab(app)
    tab.set_inventory(_inventory())
    tab.run_guide()
    assert "Prossimi passi" in tab.view.toPlainText()
