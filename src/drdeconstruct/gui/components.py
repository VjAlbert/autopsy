"""Mattoncini comuni a tutte le schede: pagina, passaggi numerati, messaggi.

Ogni scheda è una `Page`: un'intestazione con icona, titolo e sottotitolo, un
riquadro di messaggio (`Banner`) per avanzamento ed errori e una serie di
`StepCard` numerate che guidano l'utente dall'inizio alla fine.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from drdeconstruct.gui import icons
from drdeconstruct.gui.theme import ACCENT, DANGER, INFO, SUCCESS, VIOLET, WARNING

Runner = Callable[..., None]

BANNER_ICONS = {
    "info": ("help", INFO),
    "success": ("check", SUCCESS),
    "warning": ("alert", WARNING),
    "error": ("alert", DANGER),
    "busy": ("refresh", VIOLET),
}


def label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return widget


def button(
    text: str,
    on_click: Callable[[], object] | None = None,
    kind: str = "",
    icon_name: str = "",
    tooltip: str = "",
) -> QPushButton:
    """Pulsante con lo stile del tema; `kind`: "primary", "danger", "link" o vuoto."""
    btn = QPushButton(text)
    if kind:
        btn.setObjectName(kind)
    if icon_name:
        color = "#ffffff" if kind in ("primary", "danger") else "#c9d1dc"
        btn.setIcon(icons.icon(icon_name, color))
    if tooltip:
        btn.setToolTip(tooltip)
    if on_click is not None:
        btn.clicked.connect(lambda _checked=False: on_click())
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def restyle(widget: QWidget) -> None:
    """Riapplica il foglio di stile dopo aver cambiato una proprietà dinamica."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Banner(QFrame):
    """Messaggio in linea: cosa sta succedendo, cosa è andato bene o storto."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.kind = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        self._icon = QLabel()
        self._icon.setFixedSize(22, 22)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._text = label("")
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedWidth(120)
        self._bar.setTextVisible(False)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._text, 1)
        row.addWidget(self._bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    @property
    def text(self) -> str:
        return self._text.text()

    def show_message(self, kind: str, text: str) -> None:
        self.kind = kind
        self.setProperty("kind", kind)
        name, color = BANNER_ICONS[kind]
        self._icon.setPixmap(icons.pixmap(name, 20, color))
        self._text.setText(text)
        self._bar.setVisible(kind == "busy")
        restyle(self)
        self.show()

    def info(self, text: str) -> None:
        self.show_message("info", text)

    def success(self, text: str) -> None:
        self.show_message("success", text)

    def warning(self, text: str) -> None:
        self.show_message("warning", text)

    def error(self, text: str) -> None:
        self.show_message("error", text)

    def busy(self, text: str) -> None:
        self.show_message("busy", text)

    def clear(self) -> None:
        self.kind = ""
        self.hide()


class StepCard(QFrame):
    """Un passaggio numerato: titolo, spiegazione breve e i suoi controlli."""

    def __init__(self, number: int | str, title: str, hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)
        badge = QLabel(str(number))
        badge.setObjectName("stepNumber")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self.title = label(title, "stepTitle")
        self.body.addWidget(self.title)
        if hint:
            self.hint = label(hint, "hint")
            self.body.addWidget(self.hint)
        outer.addLayout(self.body, 1)

    def add(self, item) -> StepCard:
        """Aggiunge un widget o un layout al corpo del passaggio."""
        if isinstance(item, QWidget):
            self.body.addWidget(item)
        else:
            self.body.addLayout(item)
        return self


def row(*items, stretch_after: bool = False) -> QHBoxLayout:
    """Riga orizzontale; `None` tra gli elementi inserisce uno spazio elastico."""
    layout = QHBoxLayout()
    layout.setSpacing(8)
    for item in items:
        if item is None:
            layout.addStretch()
        elif isinstance(item, QWidget):
            layout.addWidget(item)
        else:
            layout.addLayout(item)
    if stretch_after:
        layout.addStretch()
    return layout


class Page(QWidget):
    """Scheda guidata: intestazione, messaggio di stato e contenuto scorrevole.

    `run(fn, on_done, busy, with_progress=False)` esegue un lavoro lento senza
    bloccare la finestra; la finestra principale aggiorna il `Banner` della
    pagina e disattiva i pulsanti in `busy_widgets` finché il lavoro è in corso.
    """

    nav_title = ""
    nav_icon = "home"

    def __init__(
        self,
        title: str,
        subtitle: str,
        icon_name: str,
        run: Runner | None = None,
        scroll: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.run = run or (lambda fn, on_done, busy, **kw: on_done(fn()))
        self.busy_widgets: list[QWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(24, 20, 24, 8)
        head.setSpacing(14)
        pic = QLabel()
        pic.setPixmap(icons.pixmap(icon_name, 34, ACCENT))
        pic.setFixedSize(38, 38)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(title, "pageTitle"))
        texts.addWidget(label(subtitle, "pageSubtitle"))
        head.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(texts, 1)
        outer.addLayout(head)

        self.banner = Banner()
        banner_box = QVBoxLayout()
        banner_box.setContentsMargins(24, 4, 24, 4)
        banner_box.addWidget(self.banner)
        outer.addLayout(banner_box)

        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(24, 8, 24, 20)
        self.body.setSpacing(12)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(self.content)
            outer.addWidget(area, 1)
        else:
            outer.addWidget(self.content, 1)

    def step(self, number: int | str, title: str, hint: str = "") -> StepCard:
        card = StepCard(number, title, hint)
        self.body.addWidget(card)
        return card

    def set_busy(self, busy: bool, message: str = "") -> None:
        for widget in self.busy_widgets:
            widget.setEnabled(not busy)
        if busy:
            self.banner.busy(message)
        elif self.banner.kind == "busy":
            self.banner.clear()
