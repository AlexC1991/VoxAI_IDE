import os
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTreeView, QFileSystemModel, 
                             QLabel, QMenu)
from PySide6.QtCore import Qt, QDir, Signal, QSize

log = logging.getLogger(__name__)

class FileTreePanel(QWidget):
    file_double_clicked = Signal(str) # Emits absolute path

    def __init__(self, start_path=None, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("background-color: #18181b;") # Zinc-950 base
        
        header = QLabel("EXPLORER")
        header.setStyleSheet("""
            color: #a1a1aa; 
            font-weight: bold; 
            font-size: 11px;
            padding: 8px 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            background-color: #18181b;
        """)
        self.layout.addWidget(header)
        
        self.model = QFileSystemModel()
        root_path = start_path if start_path else os.getcwd()
        self.model.setRootPath(root_path)
        
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(root_path))
        self.tree.setAnimated(False)
        self.tree.setIndentation(16)
        self.tree.setSortingEnabled(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setHeaderHidden(True) # VS Code style
        self.tree.setColumnHidden(1, True) # Hide Size
        self.tree.setColumnHidden(2, True) # Hide Type
        self.tree.setColumnHidden(3, True) # Hide Date
        
        # Cursor/VS Code Tree Style
        self.tree.setStyleSheet("""
            QTreeView {
                background-color: #18181b;
                color: #e4e4e7;
                border: none;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QTreeView::item {
                padding: 4px;
            }
            QTreeView::item:hover {
                background-color: #27272a;
            }
            QTreeView::item:selected {
                background-color: #3f3f46;
                color: white;
            }
            QHeaderView::section {
                background-color: #18181b;
                color: #a1a1aa;
                border: none;
            }
        """)

        # Connect to directoryLoaded to ensure we set the index after it's ready
        self.model.directoryLoaded.connect(self.on_directory_loaded)
        
        self.tree.doubleClicked.connect(self.on_double_click)
        self.layout.addWidget(self.tree)
        
        log.info(f"FileTree initialized with path: {root_path}")

    def on_directory_loaded(self, path):
        # When a directory is loaded, if it matches our root, ensure root index is set
        log.debug(f"Directory loaded: {path}")
        if path == self.model.rootPath():
            log.info(f"Setting root index for loaded path: {path}")
            self.tree.setRootIndex(self.model.index(path))

    def on_double_click(self, index):
        file_path = self.model.filePath(index)
        if not self.model.isDir(index):
            self.file_double_clicked.emit(file_path)

    def set_root_path(self, path):
        log.info(f"Requesting root path: {path}")
        if os.path.exists(path):
            self.model.setRootPath(path)
            # We also set it immediately in case it's already cached/fast
            self.tree.setRootIndex(self.model.index(path))
        else:
            log.error(f"Path does not exist: {path}")

    def refresh(self):
        """Forces the file system model to re-scan."""
        path = self.model.rootPath()
        log.info(f"Refreshing path: {path}")
        self.model.setRootPath("") # Clear
        self.model.setRootPath(path) # Reset
        self.tree.setRootIndex(self.model.index(path))
