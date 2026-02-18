"""
GGUF Model Manager — Browse, inspect, and manage local LLM models.
"""

import os
import re
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QFileDialog, QGroupBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

log = logging.getLogger(__name__)


def _get_models_dir():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "models", "llm")


def _parse_gguf_info(filename: str) -> dict:
    """Extract quantization, parameter size, and family from GGUF filename."""
    name = filename.replace(".gguf", "")

    quant_match = re.search(r'(Q\d+_K_[A-Z]+|IQ\d+_[A-Z]+|F16|F32|BF16)', name, re.IGNORECASE)
    quant = quant_match.group(1).upper() if quant_match else "Unknown"

    size_match = re.search(r'(\d+\.?\d*)\s*[Bb](?:illion)?', name)
    if not size_match:
        size_match = re.search(r'[-_](\d+\.?\d*)[Bb][-_.]', name)
    params = f"{size_match.group(1)}B" if size_match else "?"

    family_patterns = [
        (r'(?i)llama', "Llama"), (r'(?i)mistral', "Mistral"),
        (r'(?i)qwen', "Qwen"), (r'(?i)gemma', "Gemma"),
        (r'(?i)phi', "Phi"), (r'(?i)deepseek', "DeepSeek"),
        (r'(?i)codellama', "CodeLlama"), (r'(?i)dolphin', "Dolphin"),
        (r'(?i)yi', "Yi"), (r'(?i)solar', "Solar"),
        (r'(?i)command', "Command-R"), (r'(?i)falcon', "Falcon"),
        (r'(?i)vicuna', "Vicuna"), (r'(?i)openchat', "OpenChat"),
        (r'(?i)nous', "Nous"), (r'(?i)tinyllama', "TinyLlama"),
    ]
    family = "Unknown"
    for pattern, label in family_patterns:
        if re.search(pattern, name):
            family = label
            break

    return {"quant": quant, "params": params, "family": family}


def _estimate_vram_gb(file_size_gb: float, quant: str) -> float:
    """Rough VRAM estimate: file size + ~20% overhead for KV cache."""
    return round(file_size_gb * 1.2, 1)


def _get_gpu_vram_gb() -> float:
    """Detect available GPU VRAM in GB."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            mb = float(result.stdout.strip().split("\n")[0])
            return round(mb / 1024, 1)
    except Exception:
        pass
    return 0.0


class ModelManagerDialog(QDialog):
    model_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GGUF Model Manager")
        self.resize(800, 520)
        self.setStyleSheet("""
            QDialog { background: #18181b; color: #e4e4e7; }
            QGroupBox { border: 1px solid #3f3f46; border-radius: 6px; margin-top: 12px; padding-top: 18px; font-weight: bold; color: #a1a1aa; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QPushButton { background: #27272a; color: #e4e4e7; border: 1px solid #3f3f46; border-radius: 4px; padding: 6px 14px; font-family: 'Consolas', monospace; }
            QPushButton:hover { background: #3f3f46; color: #00f3ff; border-color: #00f3ff; }
            QTableWidget { background: #1c1c1f; border: 1px solid #3f3f46; color: #e4e4e7; gridline-color: #27272a; }
            QHeaderView::section { background: #27272a; color: #a1a1aa; border: none; padding: 6px; font-weight: bold; }
            QTableWidget::item:selected { background: #3f3f46; color: #00f3ff; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # GPU info bar
        self.gpu_vram = _get_gpu_vram_gb()
        gpu_label = QLabel(
            f"GPU VRAM: {self.gpu_vram} GB" if self.gpu_vram > 0
            else "GPU: Not detected (CPU-only mode)"
        )
        gpu_label.setStyleSheet("color: #ff9900; font-weight: bold; padding: 4px;")
        layout.addWidget(gpu_label)

        # Model table
        group = QGroupBox("Local GGUF Models")
        group_layout = QVBoxLayout(group)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Model", "Family", "Params", "Quant", "Size (GB)", "VRAM Est."])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 6):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(self.table.styleSheet() + "alternate-background-color: #1f1f23;")
        group_layout.addWidget(self.table)

        layout.addWidget(group)

        # Button bar
        btn_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.scan_models)
        btn_layout.addWidget(self.refresh_btn)

        self.open_dir_btn = QPushButton("Open Models Folder")
        self.open_dir_btn.clicked.connect(self._open_models_dir)
        btn_layout.addWidget(self.open_dir_btn)

        self.import_btn = QPushButton("Import Model…")
        self.import_btn.clicked.connect(self._import_model)
        btn_layout.addWidget(self.import_btn)

        btn_layout.addStretch()

        self.select_btn = QPushButton("Use Selected")
        self.select_btn.setStyleSheet(
            "background: #00f3ff; color: #18181b; font-weight: bold; border: none; padding: 8px 20px;"
        )
        self.select_btn.clicked.connect(self._use_selected)
        btn_layout.addWidget(self.select_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        self.scan_models()

    def scan_models(self):
        models_dir = _get_models_dir()
        self.table.setRowCount(0)

        if not os.path.exists(models_dir):
            os.makedirs(models_dir, exist_ok=True)
            return

        gguf_files = sorted(f for f in os.listdir(models_dir) if f.endswith(".gguf"))
        self.table.setRowCount(len(gguf_files))

        for row, filename in enumerate(gguf_files):
            filepath = os.path.join(models_dir, filename)
            size_gb = os.path.getsize(filepath) / (1024 ** 3)
            info = _parse_gguf_info(filename)
            vram_est = _estimate_vram_gb(size_gb, info["quant"])

            items = [
                filename,
                info["family"],
                info["params"],
                info["quant"],
                f"{size_gb:.1f}",
                f"{vram_est:.1f}",
            ]

            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                # Color VRAM column based on fit
                if col == 5 and self.gpu_vram > 0:
                    if vram_est <= self.gpu_vram:
                        item.setForeground(QColor("#4ec9b0"))
                    elif vram_est <= self.gpu_vram * 1.3:
                        item.setForeground(QColor("#ff9900"))
                    else:
                        item.setForeground(QColor("#f14c4c"))

                self.table.setItem(row, col, item)

        log.info("Model Manager: scanned %d GGUF models in %s", len(gguf_files), models_dir)

    def _open_models_dir(self):
        models_dir = _get_models_dir()
        os.makedirs(models_dir, exist_ok=True)
        import subprocess
        if os.name == "nt":
            subprocess.Popen(["explorer", models_dir])
        else:
            subprocess.Popen(["xdg-open", models_dir])

    def _import_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import GGUF Model", "", "GGUF Models (*.gguf)"
        )
        if not path:
            return
        import shutil
        dest = os.path.join(_get_models_dir(), os.path.basename(path))
        if os.path.exists(dest):
            QMessageBox.warning(self, "Already Exists", f"Model '{os.path.basename(path)}' already exists.")
            return
        try:
            os.makedirs(_get_models_dir(), exist_ok=True)
            shutil.copy2(path, dest)
            QMessageBox.information(self, "Imported", f"Model copied to models/llm/")
            self.scan_models()
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", str(e))

    def _use_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Select a model first.")
            return
        filename = self.table.item(row, 0).text()
        self.model_selected.emit(filename)
        self.accept()
