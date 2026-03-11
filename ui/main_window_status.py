import logging
import subprocess

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QLabel, QProgressBar, QStatusBar

from core.ai_client import AIClient
from core.settings import SettingsManager
from ui.main_window_support import OpenRouterHealthWorker


log = logging.getLogger(__name__)


def _setup_status_bar(self):
    sb = QStatusBar()
    sb.setStyleSheet(
        "QStatusBar { background: #0e0e10; color: #71717a; border-top: 1px solid #1e1e21; font-family: 'Consolas', monospace; font-size: 11px; padding: 0 4px; }"
        "QStatusBar::item { border: none; }"
    )
    self.setStatusBar(sb)

    self._status_branch = QLabel("Branch: —")
    self._status_branch.setStyleSheet("color: #71717a; padding: 0 10px; font-size: 11px;")
    self._status_branch.setToolTip("Current git branch for the open project")
    sb.addWidget(self._status_branch)

    self._status_cursor = QLabel("Ln 1, Col 1")
    self._status_cursor.setStyleSheet("color: #71717a; padding: 0 10px; font-size: 11px;")
    self._status_cursor.setToolTip("Cursor position in the active editor")
    sb.addPermanentWidget(self._status_cursor)

    self._status_encoding = QLabel("UTF-8")
    self._status_encoding.setStyleSheet("color: #52525b; padding: 0 10px; font-size: 11px;")
    self._status_encoding.setToolTip("Encoding for the active file")
    sb.addPermanentWidget(self._status_encoding)

    self._status_openrouter = QLabel("OpenRouter: inactive")
    self._status_openrouter.setToolTip("Recommended OpenRouter model based on recent health checks")
    sb.addPermanentWidget(self._status_openrouter)
    self._apply_openrouter_health_indicator({"status": "inactive", "message": "OpenRouter: inactive"})

    self._token_bar = QProgressBar()
    self._token_bar.setFixedWidth(100)
    self._token_bar.setFixedHeight(10)
    self._token_bar.setRange(0, 100)
    self._token_bar.setValue(0)
    self._token_bar.setFormat("")
    self._token_bar.setStyleSheet(
        "QProgressBar { background: #1e1e21; border: none; border-radius: 5px; }"
        "QProgressBar::chunk { background: #00f3ff; border-radius: 5px; }"
    )
    sb.addPermanentWidget(self._token_bar)

    self._status_tokens = QLabel("0 / 24K tokens")
    self._status_tokens.setStyleSheet("color: #52525b; padding: 0 8px; font-size: 11px;")
    self._status_tokens.setToolTip("Conversation history currently being sent to the model")
    sb.addPermanentWidget(self._status_tokens)

    self._branch_timer = QTimer(self)
    self._branch_timer.timeout.connect(self._refresh_branch)
    self._branch_timer.start(5000)

    self._cursor_timer = QTimer(self)
    self._cursor_timer.timeout.connect(self._refresh_cursor_pos)
    self._cursor_timer.start(200)


def _refresh_branch(self):
    if not self.project_path:
        return
    try:
        result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.project_path, capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            self._status_branch.setText(f"Branch: {result.stdout.strip()}")
    except Exception:
        pass


def update_token_count(self, count: int):
    max_tok = self.settings_manager.get_max_history_tokens()
    pct = min(100, int(count / max(max_tok, 1) * 100))
    self._token_bar.setValue(pct)
    color = "#00f3ff" if pct < 50 else ("#e5c07b" if pct < 80 else "#ef4444")
    self._token_bar.setStyleSheet(
        f"QProgressBar {{ background: #27272a; border: 1px solid #3f3f46; border-radius: 3px; }}"
        f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
    )
    disp = f"{count/1000:.1f}K" if count >= 1000 else str(count)
    self._status_tokens.setText(f"{disp} / {max_tok/1000:.0f}K tokens")
    self._status_tokens.setStyleSheet(f"color: {color}; padding: 0 8px; font-size: 11px;")


def _openrouter_health_indicator_style(status: str) -> str:
    color = {
        "healthy": "#10b981",
        "rate_limited": "#f59e0b",
        "policy_blocked": "#ef4444",
        "request_failed": "#fb7185",
        "inactive": "#52525b",
        "unknown": "#60a5fa",
    }.get(status or "unknown", "#60a5fa")
    return f"color: {color}; padding: 0 10px; font-size: 11px;"


def _apply_openrouter_health_indicator(self, indicator: dict | None = None):
    indicator = indicator or AIClient.get_openrouter_health_indicator(self.settings_manager)
    label = getattr(self, '_status_openrouter', None)
    if label is None:
        return
    message = indicator.get("message") or "OpenRouter: inactive"
    status = indicator.get("status") or "inactive"
    benchmark_model = SettingsManager.DEFAULT_BENCHMARK_MODEL.split("] ", 1)[1]
    label.setText(f"{message} • Benchmark: {benchmark_model}")
    label.setStyleSheet(self._openrouter_health_indicator_style(status))
    tooltip = indicator.get("recommended_full_model") or message
    suffix = f"Preferred benchmark model: {SettingsManager.DEFAULT_BENCHMARK_MODEL}"
    label.setToolTip(f"{tooltip}\n{suffix}" if tooltip else suffix)


def _setup_openrouter_health_refresh(self):
    if not hasattr(self, '_openrouter_health_timer') or self._openrouter_health_timer is None:
        self._openrouter_health_timer = QTimer(self)
        self._openrouter_health_timer.timeout.connect(self._queue_openrouter_health_refresh)
    else:
        self._openrouter_health_timer.stop()
    self._openrouter_health_timer.start(AIClient.OPENROUTER_BACKGROUND_REFRESH_INTERVAL_SECONDS * 1000)
    self._apply_openrouter_health_indicator()
    QTimer.singleShot(15000, self._queue_openrouter_health_refresh)


def _should_run_openrouter_health_refresh(self) -> bool:
    if self._openrouter_health_inflight or self._terminal_proc is not None:
        return False
    if getattr(self.chat_panel, 'is_processing', False):
        return False
    return AIClient.should_background_refresh(self.settings_manager)


def _queue_openrouter_health_refresh(self):
    if not self._should_run_openrouter_health_refresh():
        return
    self._openrouter_health_inflight = True
    self._openrouter_health_thread = QThread()
    self._openrouter_health_worker = OpenRouterHealthWorker()
    self._openrouter_health_worker.moveToThread(self._openrouter_health_thread)
    self._openrouter_health_thread.started.connect(self._openrouter_health_worker.run)
    self._openrouter_health_worker.finished.connect(self._handle_openrouter_health_refresh)
    self._openrouter_health_worker.finished.connect(self._openrouter_health_thread.quit)
    self._openrouter_health_worker.finished.connect(self._openrouter_health_worker.deleteLater)
    self._openrouter_health_thread.finished.connect(self._openrouter_health_thread.deleteLater)
    self._openrouter_health_thread.finished.connect(self._clear_openrouter_health_refresh_refs)
    self._openrouter_health_thread.start()


def _handle_openrouter_health_refresh(self, summary: dict):
    if summary.get("error"):
        return
    log.info(
        "OpenRouter background health refresh | probed=%s recommended=%s skipped=%s",
        summary.get("probed_models", []),
        summary.get("recommended_model"),
        summary.get("skipped_reason"),
    )
    before = (self.settings_manager.get_selected_model() or "").strip()
    selected, note = AIClient.auto_select_openrouter_model(self.settings_manager, run_probe=False)
    if selected and selected != before:
        self.chat_panel.refresh_models()
        if note and note != self._openrouter_health_last_note and self.statusBar():
            self.statusBar().showMessage(note, 7000)
            self._openrouter_health_last_note = note
    self._apply_openrouter_health_indicator()


def _clear_openrouter_health_refresh_refs(self):
    self._openrouter_health_worker = None
    self._openrouter_health_thread = None
    self._openrouter_health_inflight = False