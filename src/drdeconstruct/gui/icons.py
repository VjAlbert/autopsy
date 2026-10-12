"""Icone vettoriali disegnate nel codice: niente file esterni da impacchettare.

Ogni icona è un frammento SVG 24x24 a tratto (stile "line icon"); `icon()`
la colora e la trasforma in QIcon, `pixmap()` in un'immagine di qualsiasi
dimensione. Il logo è a colori pieni e si usa anche per l'icona della finestra.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from drdeconstruct.gui.theme import ACCENT, VIOLET

PATHS = {
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "code": '<path d="M8 7l-5 5 5 5"/><path d="M16 7l5 5-5 5"/><path d="M14 4l-4 16"/>',
    "chip": (
        '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" '
        'height="5"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>'
    ),
    "layers": (
        '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17.5l9 5 9-5"/>'
    ),
    "swap": (
        '<path d="M4 8h13"/><path d="M14 4l4 4-4 4"/><path d="M20 16H7"/><path d="M10 12l-4 4 4 4"/>'
    ),
    "globe": (
        '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
        '<path d="M12 3c2.8 3 2.8 15 0 18M12 3c-2.8 3-2.8 15 0 18"/>'
    ),
    "usb": (
        '<path d="M12 2v15"/><circle cx="12" cy="19.5" r="2.5"/><path d="M12 13l-5-3V7"/>'
        '<rect x="5.5" y="4.5" width="3" height="3"/><path d="M12 11l5-3V6"/>'
        '<circle cx="17" cy="5" r="1.5"/>'
    ),
    "house": (
        '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>'
        '<path d="M9 15.5a4.2 4.2 0 0 1 6 0"/><path d="M10.6 17.6a1.8 1.8 0 0 1 2.8 0"/>'
    ),
    "gauge": (
        '<path d="M4 18a8.5 8.5 0 1 1 16 0"/><path d="M12 14l4-5"/><circle cx="12" cy="14" r="1.4"/>'
    ),
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 3l10 18H2L12 3z"/><path d="M12 10v5"/><path d="M12 18v.5"/>',
    "folder": '<path d="M3 6h7l2 2h9v11H3z"/>',
    "play": '<path d="M7 4l13 8-13 8z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "save": '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7V3"/><rect x="8" y="13" width="8" height="5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "help": (
        '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7"/>'
        '<path d="M12 17v.5"/>'
    ),
}

LOGO_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="{ACCENT}"/><stop offset="1" stop-color="{VIOLET}"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="14" fill="#0e1116"/>
<rect x="2" y="2" width="60" height="60" rx="14" fill="none" stroke="url(#g)" stroke-width="3"/>
<g stroke="url(#g)" stroke-width="3" stroke-linecap="round" fill="none">
<path d="M22 9v6M32 9v6M42 9v6M22 49v6M32 49v6M42 49v6M9 22h6M9 32h6M9 42h6M49 22h6M49 32h6M49 42h6"/>
<rect x="16" y="16" width="32" height="32" rx="5"/>
<path d="M27 26l-6 6 6 6M37 26l6 6-6 6"/>
</g>
<path d="M14 50L50 14" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round" opacity="0.85"/>
</svg>"""


def svg(name: str, color: str = "#c9d1dc", width: float = 1.8) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
        f'stroke-linejoin="round">{PATHS[name]}</svg>'
    )


def render(svg_text: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pix


def pixmap(name: str, size: int = 20, color: str = "#c9d1dc") -> QPixmap:
    return render(svg(name, color), size)


def icon(name: str, color: str = "#c9d1dc") -> QIcon:
    result = QIcon()
    for size in (16, 20, 24, 32, 48):
        result.addPixmap(render(svg(name, color), size))
    return result


def logo_pixmap(size: int = 64) -> QPixmap:
    return render(LOGO_SVG, size)


def logo_icon() -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(logo_pixmap(size))
    return result
