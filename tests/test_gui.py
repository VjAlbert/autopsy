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
    # Inizio + 8 moduli, ognuno con la sua voce nella barra laterale
    assert win.pages.count() == 9 and win.nav.count() == 9
    assert win.current_page() is win.home_page
    assert win.backend_box.currentData() == "ollama"
    assert win.decompile_page.binary_edit.text() == ""
    assert not win.web_page.scaffold_btn.isEnabled()
    assert win.web_page.mirror_btn.isEnabled()
    win.close()


def test_home_tiles_open_every_module(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    for key, tile in win.home_page.tiles.items():
        tile.click()
        assert win.current_page() is win.page_by_key[key]
    win.close()


def test_home_shows_system_checks(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.doctor import Check
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="claude-code"))
    home = win.home_page
    home.set_checks([Check("claude-code", "Claude Code", False, "Non trovato.", fix="Installa.")])
    assert home.banner.kind == "warning" and "Non trovato" in home.banner.text
    assert not home.install_btn.isHidden() and home.login_btn.isHidden()
    home.set_checks([Check("claude-code", "Claude Code", True, "Installato.")])
    assert home.banner.kind == "success"
    assert home.install_btn.isHidden() and not home.login_btn.isHidden()
    win.close()


def test_engine_choice_is_shared_by_all_pages(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    win.backend_box.setCurrentIndex(win.backend_box.findData("api"))
    assert win.scaffold_tab._settings().backend == "api"
    assert win.analysis_page._settings().backend == "api"
    assert win.engine_dot.text().startswith("●")
    win.close()


def test_errors_show_in_the_page_that_started_the_job(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.core.errors import BackendError
    from drdeconstruct.gui.main_window import MainWindow

    def boom():
        raise BackendError("Ollama non raggiungibile")

    win = MainWindow(Settings(backend="ollama"))
    page = win.analysis_page
    page.run(boom, on_done=lambda r: None, busy="Analisi…")
    assert page.banner.kind == "busy" and not page.run_btn.isEnabled()
    win._task.wait(5000)
    app.processEvents()
    assert page.banner.kind == "error" and "Ollama" in page.banner.text
    assert page.run_btn.isEnabled()
    win.close()


def test_missing_input_is_explained_inline(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    win.analysis_page._run_analysis()
    assert win._task is None and win.analysis_page.banner.kind == "warning"
    win.decompile_page._run_decompile()
    assert "Scegli file" in win.decompile_page.banner.text
    win.web_page._run_web()
    assert "indirizzo" in win.web_page.banner.text
    win.close()


def test_sample_and_serial_log_flow_into_analysis(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    page = win.analysis_page
    page.kind_box.setCurrentIndex(page.kind_box.findData("assembly"))
    page._load_sample()
    assert "push ebp" in page.input_edit.toPlainText()

    win.devices_page.show_log("U-Boot 2016.07\nStarting kernel ...")
    assert win.devices_page.explain_btn.isEnabled()
    win.devices_page.explain_btn.click()
    assert win.current_page() is page
    assert page.kind().value == "bus_log" and "U-Boot" in page.input_edit.toPlainText()
    win.close()


def test_serial_ports_fill_the_capture_step(app):
    from drdeconstruct.acquisition.models import DeviceInfo, LinkKind
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    dev = win.devices_page
    dev.show_devices([DeviceInfo(LinkKind.SERIAL, "COM7", "USB-SERIAL CH340")])
    assert dev.port_box.currentText() == "COM7" and dev.device_list.count() == 1
    win.close()


def test_ghidra_folder_picked_in_gui(app, monkeypatch, tmp_path):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    monkeypatch.delenv("GHIDRA_INSTALL_DIR", raising=False)
    win = MainWindow(Settings(backend="ollama"))
    page = win.decompile_page
    assert page.ghidra_status.text().startswith("✗")
    support = tmp_path / "support"
    support.mkdir()
    (support / "analyzeHeadless").write_text("")
    (support / "analyzeHeadless.bat").write_text("")
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))
    page.set_ghidra_folder(str(tmp_path))
    assert page.ghidra_status.text().startswith("✓")
    win.close()


def test_processor_choice(app):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow

    win = MainWindow(Settings(backend="ollama"))
    page = win.decompile_page
    assert page.processor() is None
    page.proc_box.setCurrentIndex(page.proc_box.findData("MIPS:LE:32:default"))
    assert page.processor() == "MIPS:LE:32:default"
    page.proc_box.setEditText("ARM:BE:32:v8 scritto a mano")
    assert page.processor() == "ARM:BE:32:v8"
    win.close()


def test_web_tab_shows_readable_report(app, monkeypatch, tmp_path):
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow
    from drdeconstruct.web.extract import build_snapshot
    from drdeconstruct.web.schemas import WebAnalysis
    from tests.test_web import PAGE, WEB_PAYLOAD

    win = MainWindow(Settings(backend="ollama"))
    page = win.web_page
    snap = build_snapshot("https://rossi.test/", PAGE)
    page.show_web((snap, WebAnalysis.model_validate(WEB_PAYLOAD)))
    text = page.web_view.toPlainText()
    assert "Griglia schede" in text and '"snapshot"' not in text
    assert page.scaffold_btn.isEnabled() and page.save_json_btn.isEnabled()

    page.show_web((snap, None))
    assert not page.scaffold_btn.isEnabled()
    win.close()


def test_gui_analyzes_several_functions_with_shared_names(app, monkeypatch):
    from drdeconstruct import cli
    from drdeconstruct.config import Settings
    from drdeconstruct.gui.main_window import MainWindow
    from tests.test_improvements import PROGRAM, SchemaLLM

    llm = SchemaLLM({"FUN_80001080": ("uart_putc", "high")})
    monkeypatch.setattr(cli, "make_backend", lambda settings: llm)
    win = MainWindow(Settings(backend="ollama"))
    page = win.analysis_page
    page.kind_box.setCurrentIndex(page.kind_box.findData("pseudocode_c"))
    page.input_edit.setPlainText(PROGRAM)
    page._run_analysis()
    win._task.wait(5000)
    app.processEvents()
    text = page.output_view.toPlainText()
    # risultato leggibile, non JSON
    assert "uart_putc" in text and "Nomi comuni a tutto il programma" in text
    assert '"symbol_map"' not in text
    assert page.banner.kind == "success" and page.save_md_btn.isEnabled()
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
