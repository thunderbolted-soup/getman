"""App icon painted at runtime (no image files to ship)."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap


def app_icon() -> QIcon:
    icon = QIcon()
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
        icon.addPixmap(pix)
    return icon
