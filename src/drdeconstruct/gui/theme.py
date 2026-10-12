"""Tema scuro dell'interfaccia: colori condivisi e foglio di stile (QSS).

Tutte le schede usano gli stessi nomi di oggetto (`heading`, `hint`, `step`,
`card`, `banner`…), così l'aspetto resta coerente in tutta l'app.
"""

BG = "#0e1116"
SURFACE = "#151a21"
SURFACE_2 = "#1c222b"
BORDER = "#29313d"
TEXT = "#e6e9ef"
MUTED = "#8d96a5"
ACCENT = "#2fbf9f"
ACCENT_HOVER = "#3fd4b2"
ACCENT_DARK = "#1f8a73"
VIOLET = "#8b6cff"
DANGER = "#e5534b"
WARNING = "#d8a236"
SUCCESS = "#3fb950"
INFO = "#58a6ff"

DARK_QSS = f"""
* {{ font-family: "Segoe UI", "Inter", "Cantarell", "DejaVu Sans", sans-serif; font-size: 13px; }}
QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}

/* Barra superiore e navigazione laterale */
QFrame#topbar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QFrame#topbar QLabel, QFrame#sidebar QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 17px; font-weight: 800; color: {TEXT}; }}
QLabel#brandSub {{ color: {MUTED}; font-size: 11px; }}
QFrame#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QListWidget#nav {{ background: transparent; border: none; outline: 0; padding: 6px; }}
QListWidget#nav::item {{
    color: #b9c0cc; padding: 10px 10px; margin: 2px 0; border-radius: 8px;
}}
QListWidget#nav::item:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QListWidget#nav::item:selected {{ background: {ACCENT_DARK}; color: #ffffff; }}
QLabel#engineDot {{ font-size: 12px; padding: 4px 10px; border-radius: 10px; }}
QLabel#engineDot[state="ok"] {{ color: {SUCCESS}; background: rgba(63,185,80,0.12); }}
QLabel#engineDot[state="bad"] {{ color: {WARNING}; background: rgba(216,162,54,0.12); }}
QLabel#engineDot[state="unknown"] {{ color: {MUTED}; background: {SURFACE_2}; }}

/* Intestazione di pagina */
QLabel#pageTitle {{ font-size: 22px; font-weight: 800; }}
QLabel#pageSubtitle {{ color: {MUTED}; font-size: 13px; }}
QLabel#heading {{ font-size: 16px; font-weight: 700; }}
QLabel#hint {{ color: {MUTED}; }}
QLabel#step {{ font-weight: 700; color: {ACCENT_HOVER}; margin-top: 6px; }}

/* Passaggi numerati */
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#card QLabel#stepNumber {{
    background: {ACCENT_DARK}; color: #ffffff; font-weight: 800; border-radius: 13px;
    min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
}}
QLabel#stepTitle {{ font-size: 14px; font-weight: 700; }}

QFrame#card QStackedWidget, QFrame#card QStackedWidget > QWidget {{ background: transparent; }}

/* Schede della schermata iniziale */
QPushButton#tile {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
    padding: 14px; text-align: left; color: {TEXT}; font-weight: 600;
}}
QPushButton#tile:hover {{ border-color: {ACCENT}; background: {SURFACE_2}; }}

/* Messaggi in linea: info, successo, attenzione, errore, in corso */
QFrame#banner {{ border-radius: 10px; border: 1px solid {BORDER}; background: {SURFACE_2}; }}
QFrame#banner QLabel {{ background: transparent; }}
QFrame#banner[kind="info"] {{ border-color: {INFO}; background: rgba(88,166,255,0.10); }}
QFrame#banner[kind="success"] {{ border-color: {SUCCESS}; background: rgba(63,185,80,0.10); }}
QFrame#banner[kind="warning"] {{ border-color: {WARNING}; background: rgba(216,162,54,0.10); }}
QFrame#banner[kind="error"] {{ border-color: {DANGER}; background: rgba(229,83,75,0.10); }}
QFrame#banner[kind="busy"] {{ border-color: {VIOLET}; background: rgba(139,108,255,0.10); }}

/* Pulsanti */
QPushButton {{
    background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER};
    padding: 8px 16px; border-radius: 8px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ background: #20252d; color: #5f6672; border-color: #232a33; }}
QPushButton#primary {{ background: {ACCENT_DARK}; color: #ffffff; border: none; }}
QPushButton#primary:hover {{ background: {ACCENT}; }}
QPushButton#primary:disabled {{ background: #253029; color: #6c7a72; }}
QPushButton#danger {{ background: #8c3328; color: #ffffff; border: none; }}
QPushButton#danger:hover {{ background: {DANGER}; }}
QPushButton#danger:disabled {{ background: #2b2324; color: #6f5f5f; }}
QPushButton#link {{
    background: transparent; border: none; color: {INFO}; padding: 2px 4px; text-align: left;
}}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton:checked {{ background: {ACCENT_DARK}; color: #ffffff; }}

/* Campi */
QTextEdit, QPlainTextEdit, QLineEdit, QComboBox, QListWidget, QTextBrowser {{
    background: #0a0d12; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
    selection-background-color: {ACCENT_DARK};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER}; }}
QPlainTextEdit#code, QTextEdit#code {{
    font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; font-size: 12px;
}}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid #5b6472; background: #0a0d12;
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 10px;
    background: {SURFACE};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {MUTED}; }}
QProgressBar {{
    background: #0a0d12; border: 1px solid {BORDER}; border-radius: 6px; text-align: center;
    min-height: 10px; max-height: 14px; color: {MUTED};
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2f3743; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2f3743; border-radius: 4px; min-width: 30px; }}
QSplitter::handle {{ background: {BG}; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QMenuBar {{ background: {SURFACE}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {ACCENT_DARK}; }}
QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; }}
"""
