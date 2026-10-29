"""Toolbar icon drawn at runtime so the plugin carries no image resources."""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def calpdf_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64):
        icon.addPixmap(_pixmap(size))
    return icon


def _pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    page = QRectF(size * 0.20, size * 0.10, size * 0.52, size * 0.80)
    painter.setPen(QPen(QColor(150, 150, 150), max(1.0, size * 0.055)))
    painter.setBrush(QColor(250, 250, 250))
    painter.drawRoundedRect(page, size * 0.06, size * 0.06)

    ribbon = QRectF(size * 0.55, size * 0.10, size * 0.16, size * 0.34)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(52, 120, 246))
    painter.drawRect(ribbon)

    notch = QPainterPath()
    notch.moveTo(QPointF(ribbon.left(), ribbon.bottom()))
    notch.lineTo(QPointF(ribbon.right(), ribbon.bottom()))
    notch.lineTo(QPointF(ribbon.center().x(), ribbon.bottom() - size * 0.10))
    notch.closeSubpath()
    painter.setBrush(QColor(250, 250, 250))
    painter.drawPath(notch)

    painter.setPen(QPen(QColor(120, 120, 120), max(1.0, size * 0.045)))
    for i in range(3):
        y = size * (0.40 + i * 0.12)
        painter.drawLine(int(size * 0.29), int(y), int(size * 0.50), int(y))

    painter.end()
    return pixmap
