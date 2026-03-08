import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PySide6.QtWidgets import QSystemTrayIcon

from ui.main_window import CodingAgentIDE


class TestGuiNotifications(unittest.TestCase):
    def test_error_notifications_use_warning_icon_and_longer_timeout(self):
        compact, icon, timeout_ms = CodingAgentIDE._notification_payload(
            "OpenRouter Rate Limit",
            "OpenRouter rate limit reached for model 'qwen/qwen3-coder:free'. Try another free model."
        )

        self.assertEqual(icon, QSystemTrayIcon.Warning)
        self.assertEqual(timeout_ms, 12000)
        self.assertIn("rate limit", compact.lower())

    def test_info_notifications_are_compacted(self):
        compact, icon, timeout_ms = CodingAgentIDE._notification_payload(
            "AI Response Complete",
            "word " * 100
        )

        self.assertEqual(icon, QSystemTrayIcon.Information)
        self.assertEqual(timeout_ms, 5000)
        self.assertLessEqual(len(compact), 220)

    def test_should_run_openrouter_health_refresh_respects_busy_state(self):
        dummy = SimpleNamespace(
            _openrouter_health_inflight=False,
            _terminal_proc=None,
            chat_panel=SimpleNamespace(is_processing=False),
            settings_manager=object(),
        )

        with patch('ui.main_window.AIClient.should_background_refresh', return_value=True):
            self.assertTrue(CodingAgentIDE._should_run_openrouter_health_refresh(dummy))

        dummy.chat_panel.is_processing = True
        with patch('ui.main_window.AIClient.should_background_refresh', return_value=True):
            self.assertFalse(CodingAgentIDE._should_run_openrouter_health_refresh(dummy))

    def test_background_refresh_applies_cached_recommendation_quietly(self):
        status_bar = MagicMock()
        dummy = SimpleNamespace(
            settings_manager=MagicMock(),
            chat_panel=SimpleNamespace(refresh_models=MagicMock()),
            _openrouter_health_last_note="",
            _status_openrouter=MagicMock(),
            statusBar=lambda: status_bar,
        )
        dummy.settings_manager.get_selected_model.return_value = "[OpenRouter] qwen/qwen3-coder:free"
        dummy._openrouter_health_indicator_style = CodingAgentIDE._openrouter_health_indicator_style
        dummy._apply_openrouter_health_indicator = lambda indicator=None: CodingAgentIDE._apply_openrouter_health_indicator(dummy, indicator)

        with patch('ui.main_window.AIClient.auto_select_openrouter_model', return_value=(
            "[OpenRouter] z-ai/glm-4.5-air:free",
            "OpenRouter preflight auto-selected healthier model 'z-ai/glm-4.5-air:free'.",
        )), patch('ui.main_window.AIClient.get_openrouter_health_indicator', return_value={
            "status": "healthy",
            "message": "OpenRouter ready: z-ai/glm-4.5-air:free",
            "recommended_full_model": "[OpenRouter] z-ai/glm-4.5-air:free",
        }):
            CodingAgentIDE._handle_openrouter_health_refresh(dummy, {"probed_models": ["qwen/qwen3-coder:free"]})

        dummy.chat_panel.refresh_models.assert_called_once()
        status_bar.showMessage.assert_called_once()
        dummy._status_openrouter.setText.assert_called_with("OpenRouter ready: z-ai/glm-4.5-air:free")

    def test_apply_openrouter_health_indicator_updates_label_style(self):
        label = MagicMock()
        dummy = SimpleNamespace(
            settings_manager=MagicMock(),
            _status_openrouter=label,
            _openrouter_health_indicator_style=CodingAgentIDE._openrouter_health_indicator_style,
        )

        CodingAgentIDE._apply_openrouter_health_indicator(dummy, {
            "status": "rate_limited",
            "message": "OpenRouter cooling down: qwen/qwen3-coder:free",
            "recommended_full_model": "[OpenRouter] qwen/qwen3-coder:free",
        })

        label.setText.assert_called_once_with("OpenRouter cooling down: qwen/qwen3-coder:free")
        label.setToolTip.assert_called_once_with("[OpenRouter] qwen/qwen3-coder:free")

    def test_openrouter_notification_refreshes_indicator(self):
        status_bar = MagicMock()
        tray = MagicMock()
        tray.isSystemTrayAvailable.return_value = False
        dummy = SimpleNamespace(
            _tray=tray,
            statusBar=lambda: status_bar,
            isActiveWindow=lambda: True,
            _apply_openrouter_health_indicator=MagicMock(),
            _notification_payload=CodingAgentIDE._notification_payload,
        )

        CodingAgentIDE._show_notification(dummy, "OpenRouter Preflight", "Auto-selected healthier model")

        dummy._apply_openrouter_health_indicator.assert_called_once()
        status_bar.showMessage.assert_called_once()


if __name__ == '__main__':
    unittest.main()