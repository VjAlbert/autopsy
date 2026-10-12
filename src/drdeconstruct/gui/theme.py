"""Tema scuro dell'interfaccia (QSS)."""

DARK_QSS = """
* { font-family: "Segoe UI", "Cantarell", sans-serif; font-size: 13px; }
QMainWindow, QWidget { background: #14161b; color: #e6e6e6; }
QTabWidget::pane { border: 1px solid #2a2d36; border-radius: 8px; }
QTabBar::tab {
    background: #1c1f27; color: #b7bcc7; padding: 8px 18px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px;
}
QTabBar::tab:selected { background: #2e7d6b; color: #ffffff; }
QPushButton {
    background: #2e7d6b; color: #ffffff; border: none;
    padding: 8px 16px; border-radius: 8px; font-weight: 600;
}
QPushButton:hover { background: #359683; }
QPushButton:disabled { background: #333843; color: #7a7f8a; }
QPushButton#danger { background: #a8432f; }
QPushButton#danger:hover { background: #c24f38; }
QTextEdit, QPlainTextEdit, QLineEdit, QComboBox, QListWidget {
    background: #0f1115; border: 1px solid #2a2d36; border-radius: 8px; padding: 6px;
    selection-background-color: #2e7d6b;
}
QLabel#heading { font-size: 16px; font-weight: 700; }
QLabel#hint { color: #8b909b; }
QStatusBar { background: #0f1115; color: #8b909b; }
"""
