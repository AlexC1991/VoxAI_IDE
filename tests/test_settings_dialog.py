import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.getcwd())

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from core.settings import SettingsManager
from ui.settings_dialog import SettingsDialog


class TestSettingsDialog(unittest.TestCase):
    def _settings_mock(self):
        mgr = MagicMock()
        mgr.DEFAULT_TEST_PROVIDER_SCRIPT_PATH = SettingsManager.DEFAULT_TEST_PROVIDER_SCRIPT_PATH
        mgr.get_enabled_models.return_value = [SettingsManager.DEFAULT_TEST_MODEL]
        mgr.is_test_provider_enabled.return_value = True
        mgr.get_test_provider_script_path.return_value = ".vox/test_provider_script.json"
        mgr.list_test_provider_scenarios.return_value = [
            {"label": "test_provider_script.json", "path": ".vox/test_provider_script.json"},
            {"label": "test_provider_scenario_multi_tool_batch.json", "path": ".vox/test_provider_scenario_multi_tool_batch.json"},
        ]
        mgr.get_local_llm_url.return_value = "http://localhost:11434/v1"
        mgr.get_api_key.return_value = ""
        mgr.get_max_history_tokens.return_value = 24000
        mgr.get_auto_approve_writes.return_value = False
        mgr.get_auto_save_conversation.return_value = True
        mgr.get_web_search_enabled.return_value = False
        mgr.get_rag_enabled.return_value = True
        mgr.get_rag_top_k.return_value = 5
        mgr.get_rag_min_score.return_value = 0.0
        mgr.get_chat_user_color.return_value = "#d4d4d8"
        mgr.get_chat_ai_color.return_value = "#ff9900"
        return mgr

    def test_test_provider_dropdown_populates_and_selects_current_script(self):
        settings_mock = self._settings_mock()
        with patch('ui.settings_dialog.SettingsManager', return_value=settings_mock):
            dlg = SettingsDialog()

        ui = dlg.provider_ui['test']
        combo = ui['scenario_combo']
        self.assertIsNotNone(combo)
        self.assertEqual(combo.count(), 3)
        self.assertEqual(combo.currentData(), '.vox/test_provider_script.json')
        self.assertEqual(ui['key_input'].text(), '.vox/test_provider_script.json')
        dlg.close()

    def test_settings_dialog_uses_polished_titles_and_buttons(self):
        settings_mock = self._settings_mock()
        with patch('ui.settings_dialog.SettingsManager', return_value=settings_mock):
            dlg = SettingsDialog()

        self.assertEqual(dlg.windowTitle(), 'VoxAI IDE Settings')
        self.assertEqual(dlg.save_btn.text(), 'Save Changes')
        self.assertEqual(dlg.cancel_btn.text(), 'Close')
        dlg.close()

    def test_test_provider_selector_uses_polished_placeholder_and_reload_label(self):
        settings_mock = self._settings_mock()
        with patch('ui.settings_dialog.SettingsManager', return_value=settings_mock):
            dlg = SettingsDialog()

        ui = dlg.provider_ui['test']
        combo = ui['scenario_combo']
        self.assertEqual(combo.itemText(0), 'Choose a saved scenario…')
        self.assertEqual(ui['fetch_btn'].text(), 'Reload Scenarios')
        dlg.close()

    def test_selecting_test_scenario_updates_script_path_field(self):
        settings_mock = self._settings_mock()
        with patch('ui.settings_dialog.SettingsManager', return_value=settings_mock):
            dlg = SettingsDialog()

        ui = dlg.provider_ui['test']
        combo = ui['scenario_combo']
        combo.setCurrentIndex(2)

        self.assertEqual(
            ui['key_input'].text(),
            '.vox/test_provider_scenario_multi_tool_batch.json',
        )
        dlg.close()

    def test_reload_script_repopulates_selector_with_custom_path(self):
        settings_mock = self._settings_mock()
        settings_mock.list_test_provider_scenarios.side_effect = [
            [
                {"label": "test_provider_script.json", "path": ".vox/test_provider_script.json"},
            ],
            [
                {"label": "Custom: custom.json", "path": ".vox/custom.json"},
                {"label": "test_provider_script.json", "path": ".vox/test_provider_script.json"},
            ],
        ]

        with patch('ui.settings_dialog.SettingsManager', return_value=settings_mock), \
             patch('ui.settings_dialog.QMessageBox.information'), \
             patch('ui.settings_dialog.AIClient.clear_test_provider') as clear_mock:
            dlg = SettingsDialog()
            ui = dlg.provider_ui['test']
            ui['key_input'].setText('.vox/custom.json')
            dlg._fetch_models_for_provider('test')

        settings_mock.set_test_provider_script_path.assert_called_with('.vox/custom.json')
        clear_mock.assert_called_once()
        self.assertEqual(ui['scenario_combo'].currentData(), '.vox/custom.json')
        dlg.close()


if __name__ == '__main__':
    unittest.main()

