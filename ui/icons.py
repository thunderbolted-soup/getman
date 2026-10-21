"""Icons painted at runtime.

No icon fonts, emoji or symbol characters in the UI: on Windows the first
glyph missing from Segoe UI makes Qt load the DirectWrite font-fallback
machinery, which costs ~14 MB of private memory (measured in CI). Line icons
painted with QPainter cost a few KB and follow the theme colours.
"""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ui import theme

_cache = {}
_SIZE = 16
_SCALE = 2  # painted at 2x so icons stay crisp on HiDPI screens


def _line(p, *points):
    p.drawPolyline([QPointF(x, y) for x, y in points])


def _paint(name: str, p: QPainter):
    """Draws on a 32x32 canvas."""
    if name == "menu":
        for y in (9, 16, 23):
            _line(p, (7, y), (25, y))
    elif name == "search":
        p.drawEllipse(QRectF(6, 6, 15, 15))
        _line(p, (19.5, 19.5), (26, 26))
    elif name == "eye":
        path = QPainterPath(QPointF(4, 16))
        path.quadTo(16, 4, 28, 16)
        path.quadTo(16, 28, 4, 16)
        p.drawPath(path)
        p.drawEllipse(QRectF(12, 12, 8, 8))
    elif name == "gear":
        p.drawEllipse(QRectF(9, 9, 14, 14))
        p.drawEllipse(QRectF(13.5, 13.5, 5, 5))
        import math
        for i in range(8):
            a = i * math.pi / 4
            _line(p, (16 + 7 * math.cos(a), 16 + 7 * math.sin(a)), (16 + 11 * math.cos(a), 16 + 11 * math.sin(a)))
    elif name == "more":
        p.setBrush(p.pen().color())
        for x in (8, 16, 24):
            p.drawEllipse(QPointF(x, 16), 1.6, 1.6)
    elif name == "close":
        _line(p, (9, 9), (23, 23))
        _line(p, (23, 9), (9, 23))
    elif name == "plus":
        _line(p, (16, 7), (16, 25))
        _line(p, (7, 16), (25, 16))
    elif name == "wrap":
        path = QPainterPath(QPointF(6, 9))
        path.lineTo(22, 9)
        path.arcTo(QRectF(17, 9, 10, 10), 90, -180)
        path.lineTo(10, 19)
        p.drawPath(path)
        _line(p, (14, 15), (10, 19), (14, 23))
    elif name == "copy":
        p.drawRoundedRect(QRectF(11, 11, 14, 15), 2.5, 2.5)
        _line(p, (7, 21), (7, 8.5), (8.5, 7), (20, 7))
    elif name == "download":
        _line(p, (16, 6), (16, 20))
        _line(p, (10, 14), (16, 20), (22, 14))
        _line(p, (8, 26), (24, 26))
    elif name == "up":
        _line(p, (9, 19), (16, 12), (23, 19))
    elif name == "down":
        _line(p, (9, 13), (16, 20), (23, 13))


def icon(name: str, color: str = None) -> QIcon:
    color = color or theme.color("text_dim")
    key = (name, color)
    if key not in _cache:
        pix = QPixmap(_SIZE * _SCALE, _SIZE * _SCALE)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        _paint(name, p)
        p.end()
        pix.setDevicePixelRatio(_SCALE)
        _cache[key] = QIcon(pix)
    return _cache[key]


def set_icon(button, name: str, size: int = _SIZE):
    """Sets a painted icon and remembers its name so a theme switch can repaint it."""
    button.setProperty("iconName", name)
    button.setIcon(icon(name))
    button.setIconSize(QSize(size, size))


def refresh_icons(root):
    from PySide6.QtWidgets import QAbstractButton
    for button in root.findChildren(QAbstractButton):
        name = button.property("iconName")
        if name:
            button.setIcon(icon(name))


def app_icon() -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        p.fillPath(path, QColor("#7c6cf2"))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(size * 0.62))
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(0, -size * 0.03, size, size), Qt.AlignmentFlag.AlignCenter, "G")
        p.end()
        result.addPixmap(pix)
    return result
