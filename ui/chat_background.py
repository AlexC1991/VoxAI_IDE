import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QWidget


log = logging.getLogger(__name__)


class WatermarkContainer(QWidget):
    """Layer 1 & 2: Base Gray + Background Image."""

    def __init__(self, parent=None, logo_path=None):
        super().__init__(parent)
        self.logo = None
        if logo_path:
            logo_path = os.path.realpath(logo_path)
            if os.path.exists(logo_path):
                self.logo = QPixmap(logo_path)
                if self.logo.isNull():
                    log.error("WatermarkContainer: Failed to load logo from %s", logo_path)
                else:
                    log.info("WatermarkContainer: Loaded logo %sx%s", self.logo.width(), self.logo.height())
            else:
                log.warning("WatermarkContainer: Logo path does not exist: %s", logo_path)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#18181b"))
        if self.logo and not self.logo.isNull():
            vw, vh = self.width(), self.height()
            if vw > 0 and vh > 0:
                scaled_logo = self.logo.scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                if not scaled_logo.isNull():
                    painter.setOpacity(1.0)
                    painter.drawPixmap(0, 0, scaled_logo)


__all__ = ["WatermarkContainer"]