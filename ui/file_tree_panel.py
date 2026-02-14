import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTreeView, QFileSystemModel, 
                             QLabel, QMenu)
from PySide6.QtCore import Qt, QDir, Signal

class FileTreePanel(QWidget):
    file_double_clicked = Signal(str) # Emits absolute path

    def __init__(self, start_path=None, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        header = QLabel("Project Browser")
        header.setStyleSheet("font-weight: bold; padding: 5px;")
        self.layout.addWidget(header)
        
        self.model = QFileSystemModel()
        root_path = start_path if start_path else os.getcwd()
        self.model.setRootPath(root_path)
        
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(root_path))
        self.tree.setAnimated(False)
        self.tree.setIndentation(20)
        self.tree.setSortingEnabled(True)
        self.tree.setColumnWidth(0, 200)
        
        # Hide extra columns (Size, Type, Date) for cleaner view, or keep them if needed
        # self.tree.hideColumn(1)
        # self.tree.hideColumn(2)
        # self.tree.hideColumn(3)

        self.tree.doubleClicked.connect(self.on_double_click)
        self.layout.addWidget(self.tree)

    def on_double_click(self, index):
        file_path = self.model.filePath(index)
        if not self.model.isDir(index):
            self.file_double_clicked.emit(file_path)

    def set_root_path(self, path):
        if os.path.exists(path):
            self.model.setRootPath(path)
            self.tree.setRootIndex(self.model.index(path))

    def refresh(self):
        """Forces the file system model to re-scan."""
        # QFileSystemModel watches automatically, but sometimes needs a nudge
        # re-setting root path can help, or just ensuring we are looking at the right place.
        path = self.model.rootPath()
        self.model.setRootPath("") # Clear
        self.model.setRootPath(path) # Reset
        self.tree.setRootIndex(self.model.index(path))
