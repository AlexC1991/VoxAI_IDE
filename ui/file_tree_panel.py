import os
import shutil
import subprocess
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeView, QFileSystemModel, QLabel,
    QStyledItemDelegate, QMenu, QInputDialog, QMessageBox, QLineEdit,
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QRect
from PySide6.QtGui import QPainter, QColor

log = logging.getLogger(__name__)


class GitStatusCache:
    """Runs 'git status --porcelain' and caches results."""

    STATUS_COLORS = {
        'M': QColor("#e5c07b"),
        'A': QColor("#98c379"),
        '?': QColor("#61afef"),
        'D': QColor("#e06c75"),
        'R': QColor("#c678dd"),
        'C': QColor("#c678dd"),
        'U': QColor("#e06c75"),
    }

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._root: str = ""

    def refresh(self, root: str):
        self._root = root
        self._cache.clear()
        if not root or not os.path.isdir(os.path.join(root, ".git")):
            return
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "-uall"],
                cwd=root, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return
            for line in result.stdout.splitlines():
                if len(line) < 4:
                    continue
                xy = line[:2]
                path = line[3:].strip().strip('"')
                status = xy[1] if xy[1] != ' ' else xy[0]
                self._cache[path] = status
                parts = path.split("/")
                for i in range(1, len(parts)):
                    parent = "/".join(parts[:i])
                    if parent not in self._cache:
                        self._cache[parent] = status
        except Exception as e:
            log.debug("Git status refresh failed: %s", e)

    def get_status(self, abs_path: str) -> str | None:
        if not self._root:
            return None
        try:
            rel = os.path.relpath(abs_path, self._root).replace("\\", "/")
        except ValueError:
            return None
        return self._cache.get(rel)

    def get_color(self, abs_path: str) -> QColor | None:
        status = self.get_status(abs_path)
        return self.STATUS_COLORS.get(status) if status else None


class GitStatusDelegate(QStyledItemDelegate):
    def __init__(self, model: QFileSystemModel, git_cache: GitStatusCache, parent=None):
        super().__init__(parent)
        self._model = model
        self._git = git_cache

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)
        file_path = self._model.filePath(index)
        color = self._git.get_color(file_path)
        if color is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        dot_size = 6
        x = option.rect.right() - dot_size - 6
        y = option.rect.center().y() - dot_size // 2
        painter.drawEllipse(QRect(x, y, dot_size, dot_size))
        painter.restore()


class FileTreePanel(QWidget):
    file_double_clicked = Signal(str)
    file_created = Signal(str)
    file_deleted = Signal(str)
    file_renamed = Signal(str, str)

    def __init__(self, start_path=None, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("background-color: #18181b;")

        # Filter bar
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter files…")
        self.filter_input.setStyleSheet(
            "background: #27272a; color: #e4e4e7; border: 1px solid #3f3f46; "
            "border-radius: 3px; padding: 4px 8px; margin: 4px 8px; "
            "font-size: 11px; font-family: 'Consolas', monospace;")
        self.filter_input.textChanged.connect(self._apply_filter)
        self._layout.addWidget(self.filter_input)

        header = QLabel("EXPLORER")
        header.setStyleSheet(
            "color: #a1a1aa; font-weight: bold; font-size: 11px; "
            "padding: 4px 10px; text-transform: uppercase; letter-spacing: 1px; "
            "background-color: #18181b;")
        self._layout.addWidget(header)

        self.model = QFileSystemModel()
        root_path = start_path or os.getcwd()
        self.model.setRootPath(root_path)

        self._git_cache = GitStatusCache()

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(root_path))
        self.tree.setAnimated(False)
        self.tree.setIndentation(16)
        self.tree.setSortingEnabled(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setHeaderHidden(True)
        self.tree.setColumnHidden(1, True)
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnHidden(3, True)

        self._git_delegate = GitStatusDelegate(self.model, self._git_cache, self.tree)
        self.tree.setItemDelegateForColumn(0, self._git_delegate)

        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        self.tree.setStyleSheet("""
            QTreeView {
                background-color: #18181b; color: #e4e4e7; border: none;
                font-family: 'Segoe UI', sans-serif; font-size: 13px;
            }
            QTreeView::item { padding: 4px; }
            QTreeView::item:hover { background-color: #27272a; }
            QTreeView::item:selected { background-color: #3f3f46; color: white; }
            QHeaderView::section {
                background-color: #18181b; color: #a1a1aa; border: none;
            }
        """)

        self.model.directoryLoaded.connect(self.on_directory_loaded)
        self.tree.doubleClicked.connect(self.on_double_click)
        self._layout.addWidget(self.tree)

        self._git_timer = QTimer(self)
        self._git_timer.timeout.connect(self._refresh_git_status)
        self._git_timer.start(5000)
        self._refresh_git_status()
        log.info("FileTree initialized: %s", root_path)

    # --- Context menu ---
    def _show_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #27272a; border: 1px solid #3f3f46; padding: 4px; }"
            "QMenu::item { padding: 6px 20px; color: #e4e4e7; border-radius: 3px; }"
            "QMenu::item:selected { background: #3f3f46; color: #00f3ff; }")

        if index.isValid():
            path = self.model.filePath(index)
            is_dir = self.model.isDir(index)

            if is_dir:
                menu.addAction("New File…", lambda: self._new_file(path))
                menu.addAction("New Folder…", lambda: self._new_folder(path))
                menu.addSeparator()

            menu.addAction("Rename…", lambda: self._rename(path))
            menu.addAction("Delete", lambda: self._delete(path))
            menu.addSeparator()
            menu.addAction("Copy Path", lambda: self._copy_path(path))
            menu.addAction("Copy Relative Path",
                           lambda: self._copy_path(path, relative=True))
            menu.addSeparator()
            menu.addAction("Reveal in Explorer",
                           lambda: self._reveal(path))
        else:
            root = self.model.rootPath()
            menu.addAction("New File…", lambda: self._new_file(root))
            menu.addAction("New Folder…", lambda: self._new_folder(root))
            menu.addSeparator()
            menu.addAction("Refresh", self.refresh)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _new_file(self, parent_dir):
        name, ok = QInputDialog.getText(
            self, "New File", "File name:", QLineEdit.Normal, "")
        if ok and name:
            path = os.path.join(parent_dir, name)
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('')
                self.file_created.emit(path)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _new_folder(self, parent_dir):
        name, ok = QInputDialog.getText(
            self, "New Folder", "Folder name:", QLineEdit.Normal, "")
        if ok and name:
            path = os.path.join(parent_dir, name)
            try:
                os.makedirs(path, exist_ok=True)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _rename(self, path):
        old_name = os.path.basename(path)
        new_name, ok = QInputDialog.getText(
            self, "Rename", "New name:", QLineEdit.Normal, old_name)
        if ok and new_name and new_name != old_name:
            new_path = os.path.join(os.path.dirname(path), new_name)
            try:
                os.rename(path, new_path)
                self.file_renamed.emit(path, new_path)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _delete(self, path):
        name = os.path.basename(path)
        reply = QMessageBox.question(
            self, "Delete",
            f"Delete '{name}'?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self.file_deleted.emit(path)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _copy_path(self, path, relative=False):
        from PySide6.QtWidgets import QApplication
        text = path
        if relative:
            try:
                text = os.path.relpath(path, self.model.rootPath())
            except ValueError:
                pass
        QApplication.clipboard().setText(text)

    def _reveal(self, path):
        target = path if os.path.isdir(path) else os.path.dirname(path)
        try:
            if os.name == 'nt':
                os.startfile(target)
            elif os.uname().sysname == 'Darwin':
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as e:
            log.error("Reveal failed: %s", e)

    # --- Filter ---
    def _apply_filter(self, text):
        if text.strip():
            self.model.setNameFilters([f"*{text}*"])
            self.model.setNameFilterDisables(False)
        else:
            self.model.setNameFilters([])
            self.model.setNameFilterDisables(True)

    # --- Git ---
    def _refresh_git_status(self):
        root = self.model.rootPath()
        if root:
            self._git_cache.refresh(root)
            self.tree.viewport().update()

    def on_directory_loaded(self, path):
        if path == self.model.rootPath():
            self.tree.setRootIndex(self.model.index(path))

    def on_double_click(self, index):
        file_path = self.model.filePath(index)
        if not self.model.isDir(index):
            self.file_double_clicked.emit(file_path)

    def set_root_path(self, path):
        if os.path.exists(path):
            self.model.setRootPath(path)
            self.tree.setRootIndex(self.model.index(path))
            self._refresh_git_status()

    def refresh(self):
        path = self.model.rootPath()
        self.model.setRootPath("")
        self.model.setRootPath(path)
        self.tree.setRootIndex(self.model.index(path))
        self._refresh_git_status()
