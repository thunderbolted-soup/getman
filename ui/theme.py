"""Colour tokens, QSS and syntax palettes for the dark and light themes."""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

PALETTES = {
    "dark": {
        "bg": "#16181d", "surface": "#1c1f25", "surface2": "#22262d", "surface3": "#2a2f37",
        "border": "#2e333c", "border_strong": "#3a404b", "text": "#e3e6eb", "text_dim": "#8b93a2",
        "text_faint": "#5d6573", "accent": "#7c6cf2", "accent_hover": "#8e80ff", "accent_text": "#ffffff",
        "selection": "#3a3470", "success": "#3fb950", "warning": "#d29922", "danger": "#f0524f",
        "info": "#4c9aff",
    },
    "light": {
        "bg": "#f3f4f7", "surface": "#ffffff", "surface2": "#f7f8fa", "surface3": "#eceef3",
        "border": "#dfe2e8", "border_strong": "#c9ced8", "text": "#1d2129", "text_dim": "#626b7a",
        "text_faint": "#9aa1ad", "accent": "#6656e0", "accent_hover": "#5545d0", "accent_text": "#ffffff",
        "selection": "#dcd8ff", "success": "#1a7f37", "warning": "#9a6700", "danger": "#cf222e",
        "info": "#0969da",
    },
}

METHOD_COLORS = {
    "dark": {"GET": "#3fb950", "POST": "#e3a008", "PUT": "#4c9aff", "PATCH": "#b083f0",
             "DELETE": "#f0524f", "HEAD": "#39c5cf", "OPTIONS": "#db61a2"},
    "light": {"GET": "#1a7f37", "POST": "#9a6700", "PUT": "#0969da", "PATCH": "#8250df",
              "DELETE": "#cf222e", "HEAD": "#1b7c83", "OPTIONS": "#bf3989"},
}

# Monokai for the dark theme; a darker-ink variant that stays readable on white.
SYNTAX = {
    "dark": {"key": "#f92672", "string": "#e6db74", "number": "#ae81ff", "keyword": "#66d9ef",
             "punct": "#f8f8f2", "comment": "#75715e", "tag": "#f92672", "attr": "#a6e22e",
             "function": "#a6e22e", "variable": "#fd971f", "var_missing": "#f0524f"},
    "light": {"key": "#c7254e", "string": "#8a7a00", "number": "#7c3aed", "keyword": "#0b7ea5",
              "punct": "#333333", "comment": "#8e8e7e", "tag": "#c7254e", "attr": "#3f7f00",
              "function": "#3f7f00", "variable": "#c45d00", "var_missing": "#cf222e"},
}

_current = "dark"


def current() -> str:
    return _current


def color(token: str) -> str:
    return PALETTES[_current][token]


def method_color(method: str) -> str:
    return METHOD_COLORS[_current].get(method.upper(), PALETTES[_current]["text_dim"])


def status_color(status: int) -> str:
    if status < 300:
        return color("success")
    if status < 400:
        return color("info")
    if status < 500:
        return color("warning")
    return color("danger")


def syntax(token: str) -> str:
    return SYNTAX[_current][token]


def mono_font(size: int = 10) -> QFont:
    font = QFont()
    font.setFamilies(["JetBrains Mono", "Cascadia Code", "Cascadia Mono", "Consolas", "SF Mono", "Menlo",
                      "DejaVu Sans Mono", "Liberation Mono", "monospace"])
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    if not QFontDatabase.hasFamily(font.family()):
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(size)
    return font


def rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(alpha * 255)})"


_GLYPHS = {"check": [(7, 14.5), (12, 19.5), (21, 8.5)], "chevron": [(8, 11), (14, 17), (20, 11)]}


def _glyph_image(name: str, color: str) -> str:
    """Small line icons for QSS (checkmark, combo arrow), painted once and
    cached as PNG: QSS can't take inline images and an SVG plugin costs memory."""
    import os
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainter, QPen, QPixmap
    from core.paths import data_path
    path = data_path("cache", f"{name}-{color.lstrip('#')}.png")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pix = QPixmap(28, 28)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(x, y) for x, y in _GLYPHS[name]])
        painter.end()
        pix.save(path)
    return path.replace("\\", "/")


def _qss(p: dict) -> str:
    check = _glyph_image("check", p["accent_text"])
    chevron = _glyph_image("chevron", p["text_dim"])
    return f"""
QMainWindow, QDialog {{ background: {p['bg']}; }}
QWidget#Sidebar, QWidget#TopBar, QWidget#Card {{ background: {p['surface']}; }}
QWidget#TopBar {{ border-bottom: 1px solid {p['border']}; }}
QWidget#Sidebar {{ border-right: 1px solid {p['border']}; }}
QWidget#Workspace {{ background: {p['bg']}; }}
QLabel {{ background: transparent; }}
QLabel#Dim, QLabel[dim="true"] {{ color: {p['text_dim']}; }}
QLabel#Faint {{ color: {p['text_faint']}; }}
QLabel#SectionTitle {{ color: {p['text_dim']}; font-weight: 600; }}
QLabel#Title {{ font-size: 15px; font-weight: 600; }}
QLabel#Brand {{ font-weight: 700; font-size: 14px; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 6px;
    selection-background-color: {p['selection']}; selection-color: {p['text']};
}}
QLineEdit {{ padding: 5px 8px; }}
QComboBox {{ padding: 4px 8px; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {p['accent']};
}}
QLineEdit[error="true"], QPlainTextEdit[error="true"] {{ border-color: {p['danger']}; }}
QLineEdit:disabled {{ color: {p['text_faint']}; }}
QLineEdit#UrlEdit {{ border: none; background: transparent; padding: 7px 6px; font-size: 13px; }}
QWidget#UrlBar {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; }}
QWidget#UrlBar[focused="true"] {{ border-color: {p['accent']}; }}
QLineEdit#SearchEdit {{ padding: 6px 8px; }}
QPlainTextEdit#CodeEditor, QPlainTextEdit#Console {{ border-radius: 6px; }}
QPlainTextEdit#ResponseBody {{ border: none; border-radius: 0; background: {p['surface']}; }}

QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 11px; height: 11px; }}
QComboBox QAbstractItemView {{
    background: {p['surface']}; border: 1px solid {p['border_strong']};
    selection-background-color: {p['surface3']}; selection-color: {p['text']}; padding: 4px;
}}
QComboBox#MethodCombo {{ font-weight: 700; border: none; background: transparent; padding: 6px 8px; }}
QComboBox#EnvCombo {{ min-width: 150px; }}

QPushButton {{
    background: {p['surface3']}; border: 1px solid {p['border']}; border-radius: 6px;
    padding: 6px 14px; color: {p['text']};
}}
QPushButton:hover {{ background: {p['border']}; }}
QPushButton:pressed {{ background: {p['border_strong']}; }}
QPushButton:disabled {{ color: {p['text_faint']}; }}
QPushButton#Primary {{ background: {p['accent']}; border-color: {p['accent']}; color: {p['accent_text']};
    font-weight: 600; }}
QPushButton#Primary:hover {{ background: {p['accent_hover']}; }}
QPushButton#Danger, QPushButton#Primary[sending="true"] {{
    background: {p['danger']}; border-color: {p['danger']}; color: #ffffff; font-weight: 600; }}
QPushButton#Link {{ background: transparent; border: none; color: {p['accent']}; padding: 2px 4px; }}
QPushButton#Link:hover {{ text-decoration: underline; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px 6px;
    color: {p['text_dim']}; }}
QToolButton:hover {{ background: {p['surface3']}; color: {p['text']}; }}
QToolButton:checked {{ background: {p['surface3']}; color: {p['text']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#Segment {{ padding: 5px 12px; font-weight: 600; }}
QToolButton#Segment:checked {{ background: {p['surface3']}; color: {p['text']}; border-color: {p['border']}; }}

QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {p['text_dim']}; padding: 7px 12px; border: none;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {p['text']}; }}
QTabBar::tab:selected {{ color: {p['text']}; border-bottom: 2px solid {p['accent']}; }}
QTabBar#DocTabs {{ background: {p['surface']}; }}
QTabBar#DocTabs::tab {{ padding: 8px 6px 8px 10px; min-width: 110px; max-width: 220px;
    border-right: 1px solid {p['border']}; border-bottom: 2px solid transparent; }}
QTabBar#DocTabs::tab:selected {{ background: {p['bg']}; border-bottom: 2px solid {p['accent']}; }}
QToolButton#TabClose {{ padding: 0px 3px; margin-left: 4px; font-size: 10px; color: {p['text_faint']}; }}
QToolButton#TabClose:hover {{ color: {p['text']}; background: {p['surface3']}; }}
QTabBar QToolButton {{ background: {p['surface']}; border: none; }}

QTreeView, QListView, QTableView {{ outline: 0; }}
QTreeView, QListView, QTableView, QTreeWidget, QListWidget, QTableWidget {{
    background: transparent; border: none; alternate-background-color: {p['surface2']};
    selection-background-color: {p['surface3']}; selection-color: {p['text']};
}}
QTreeView::item, QListView::item {{ padding: 3px 2px; border-radius: 4px; }}
QTreeView::item:hover, QListView::item:hover {{ background: {p['surface2']}; }}
QTreeView::item:selected, QListView::item:selected {{ background: {p['surface3']}; color: {p['text']}; }}
QTableView {{ gridline-color: {p['border']}; }}
QTableView::item {{ padding: 2px 4px; }}
QTableView::item:selected {{ background: {p['surface3']}; color: {p['text']}; }}
QHeaderView::section {{ background: {p['surface']}; color: {p['text_dim']}; border: none;
    border-bottom: 1px solid {p['border']}; border-right: 1px solid {p['border']}; padding: 5px 6px; }}
QTableCornerButton::section {{ background: {p['surface']}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {p['border_strong']}; border-radius: 4px; min-height: 24px; min-width: 24px;
    margin: 2px; }}
QScrollBar::handle:hover {{ background: {p['text_faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {p['border']}; }}
QSplitter::handle:hover {{ background: {p['accent']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QMenu {{ background: {p['surface']}; border: 1px solid {p['border_strong']}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p['surface3']}; }}
QMenu::item:disabled {{ color: {p['text_faint']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 4px 6px; }}

QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
    padding: 5px 7px; border-radius: 4px; }}
QCheckBox {{ spacing: 6px; background: transparent; }}
QCheckBox::indicator, QTableView::indicator, QTreeView::indicator, QListView::indicator {{
    width: 14px; height: 14px; border: 1px solid {p['border_strong']}; border-radius: 4px; background: {p['surface2']}; }}
QCheckBox::indicator:hover, QTableView::indicator:hover, QTreeView::indicator:hover {{ border-color: {p['accent']}; }}
QCheckBox::indicator:checked, QTableView::indicator:checked, QTreeView::indicator:checked,
QListView::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url({check}); }}
QTreeView::indicator:indeterminate {{ background: {rgba(p['accent'], 0.45)}; border-color: {p['accent']}; }}
QRadioButton {{ spacing: 6px; background: transparent; }}
QGroupBox {{ border: 1px solid {p['border']}; border-radius: 8px; margin-top: 14px; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p['text_dim']}; }}
QListView#CompleterPopup {{ background: {p['surface']}; border: 1px solid {p['border_strong']};
    border-radius: 6px; padding: 3px; }}
QFrame#Popup {{ background: {p['surface']}; border: 1px solid {p['border_strong']}; border-radius: 10px; }}
QFrame#HLine {{ background: {p['border']}; max-height: 1px; min-height: 1px; }}
QWidget#FindBar {{ background: {p['surface2']}; border-bottom: 1px solid {p['border']}; }}
QWidget#DropZone {{ border: 2px dashed {p['border_strong']}; border-radius: 10px; background: {p['surface2']}; }}
QWidget#DropZone[hover="true"] {{ border-color: {p['accent']}; }}
QStatusBar {{ background: {p['surface']}; color: {p['text_dim']}; border-top: 1px solid {p['border']}; }}
"""


def apply_theme(app: QApplication, name: str):
    global _current
    _current = name if name in PALETTES else "dark"
    p = PALETTES[_current]
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: p["bg"], QPalette.ColorRole.WindowText: p["text"],
        QPalette.ColorRole.Base: p["surface2"], QPalette.ColorRole.AlternateBase: p["surface"],
        QPalette.ColorRole.Text: p["text"], QPalette.ColorRole.Button: p["surface3"],
        QPalette.ColorRole.ButtonText: p["text"], QPalette.ColorRole.Highlight: p["selection"],
        QPalette.ColorRole.HighlightedText: p["text"], QPalette.ColorRole.ToolTipBase: p["surface"],
        QPalette.ColorRole.ToolTipText: p["text"], QPalette.ColorRole.PlaceholderText: p["text_faint"],
        QPalette.ColorRole.Link: p["accent"], QPalette.ColorRole.Mid: p["border"],
        QPalette.ColorRole.Dark: p["border_strong"], QPalette.ColorRole.Light: p["surface3"],
    }
    for role, value in roles.items():
        pal.setColor(role, QColor(value))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(p["text_faint"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(p["text_faint"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(p["text_faint"]))
    app.setPalette(pal)
    app.setStyleSheet(_qss(p))
