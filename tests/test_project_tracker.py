import os
import sys
import unittest

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
sys.path.append(os.getcwd())

from ui.main_window import CodingAgentIDE
from ui.project_tracker_panel import ProjectTrackerPanel
from core.settings import SettingsManager


class _FakeToggle:
    def __init__(self, visible=False):
        self._visible = visible
        self.checked = None

    def isVisible(self):
        return self._visible

    def setVisible(self, visible):
        self._visible = visible

    def toggle(self):
        self._visible = not self._visible

    def setChecked(self, checked):
        self.checked = checked


class _FakeSplitter(_FakeToggle):
    def __init__(self, sizes, visible=True):
        super().__init__(visible=visible)
        self._sizes = list(sizes)

    def sizes(self):
        return list(self._sizes)

    def setSizes(self, sizes):
        self._sizes = list(sizes)


class _FakeTrackerPanel(_FakeToggle):
    def __init__(self, visible=True):
        super().__init__(visible=visible)
        self.state = None

    def update_state(self, state):
        self.state = state


class _FakeEditorPanel:
    def __init__(self):
        self.reloaded = []
        self.loaded = []
        self.diffs = []
        self.reload_result = False

    def reload_open_file(self, path, highlight=True):
        self.reloaded.append((path, highlight))
        return self.reload_result

    def load_file(self, path):
        self.loaded.append(path)

    def show_diff(self, file_path, diff_text, activate=True):
        self.diffs.append((file_path, diff_text, activate))


class TestProjectTracker(unittest.TestCase):
    def test_project_tracker_panel_renders_tasks_and_changes(self):
        panel = ProjectTrackerPanel()
        panel.update_state(
            {
                "goal": "Keep a stable plan visible.",
                "tasks": [
                    {"title": "Inspect the task and gather grounded evidence", "status": "complete"},
                    {"title": "Validate the latest change with the smallest useful command", "status": "current"},
                ],
                "session_changes": [
                    {
                        "file_path": os.path.join(os.getcwd(), "ui", "chat_panel.py"),
                        "display_path": "ui/chat_panel.py",
                        "diff_preview": "@@\n- old line\n+ new line",
                        "diff_text": "@@\n- old line\n+ new line",
                    }
                ],
            }
        )

        self.assertEqual(panel.task_goal_label.text(), "Goal: Keep a stable plan visible.")
        self.assertEqual(panel.overview_label.text(), "Progress: 1/2 complete • 0 pending • 1 changed file(s).")
        self.assertEqual(panel.task_stats_label.text(), "1/2 complete")
        self.assertEqual(panel.task_current_label.text(), "Current focus: Validate the latest change with the smallest useful command")
        self.assertEqual(panel.task_list.count(), 2)
        self.assertEqual(panel.task_list.item(0).text(), "[x] COMPLETE Inspect the task and gather grounded evidence")
        self.assertEqual(panel.task_list.item(1).text(), "[>] CURRENT  Validate the latest change with the smallest useful command")
        self.assertEqual(panel.change_count_label.text(), "1 entry")
        self.assertIn("1 captured change(s) across 1 file(s)", panel.change_summary_label.text())
        self.assertEqual(panel.change_list.count(), 1)
        self.assertEqual(panel.change_list.item(0).text(), "ui/chat_panel.py  (+1/-1)")
        self.assertIn("+ new line", panel.change_preview.toPlainText())

    def test_project_tracker_panel_emits_selected_change(self):
        panel = ProjectTrackerPanel()
        panel.update_state(
            {
                "goal": "Keep a stable plan visible.",
                "tasks": [],
                "session_changes": [
                    {
                        "file_path": os.path.join(os.getcwd(), "ui", "chat_panel.py"),
                        "display_path": "ui/chat_panel.py",
                        "diff_preview": "@@\n- old line\n+ new line",
                        "diff_text": "@@\n- old line\n+ new line",
                    }
                ],
            }
        )
        emitted = []
        panel.change_open_requested.connect(lambda file_path, diff_text: emitted.append((file_path, diff_text)))

        panel._emit_selected_change(panel.change_list.item(0))

        self.assertEqual(len(emitted), 1)
        self.assertTrue(emitted[0][0].endswith(os.path.join("ui", "chat_panel.py")))
        self.assertIn("+ new line", emitted[0][1])

    def test_main_window_tracker_helpers_manage_left_rail_state(self):
        window = type('FakeWindow', (), {})()
        window.project_tracker_panel = _FakeTrackerPanel(visible=True)
        window.history_sidebar = _FakeToggle(visible=False)
        window.left_sidebar_splitter = _FakeSplitter([1, 0], visible=True)
        window.main_splitter = _FakeSplitter([0, 700, 500], visible=True)
        window._ib_tracker = _FakeToggle()
        window._ib_history = _FakeToggle()
        window.chat_panel = type('FakeChatPanel', (), {
            'project_tracker_state': lambda self: {
                'goal': 'Track the current work and diffs.',
                'tasks': [{'title': 'Inspect the task and gather grounded evidence', 'status': 'complete'}],
                'session_changes': [{'display_path': 'ui/chat_panel.py', 'diff_preview': '@@\n- old\n+ new', 'diff_text': '@@\n- old\n+ new'}],
            }
        })()

        CodingAgentIDE._sync_left_sidebar_layout(window, force_open=True)
        CodingAgentIDE._refresh_project_tracker(window)

        self.assertTrue(window.left_sidebar_splitter.isVisible())
        self.assertTrue(window._ib_tracker.checked)
        self.assertFalse(window._ib_history.checked)
        self.assertGreaterEqual(window.main_splitter.sizes()[0], 280)
        self.assertEqual(window.left_sidebar_splitter.sizes(), [1, 0])
        self.assertEqual(window.project_tracker_panel.state['goal'], 'Track the current work and diffs.')
        self.assertEqual(window.project_tracker_panel.state['session_changes'][0]['display_path'], 'ui/chat_panel.py')

    def test_main_window_open_project_tracker_change_loads_file_and_diff(self):
        with open("tmp_tracker_target.txt", "w", encoding="utf-8") as handle:
            handle.write("hello\n")
        self.addCleanup(lambda: os.path.exists("tmp_tracker_target.txt") and os.remove("tmp_tracker_target.txt"))

        window = type('FakeWindow', (), {})()
        window.project_path = os.getcwd()
        window.editor_panel = _FakeEditorPanel()
        window._ensure_editor_visible_for_diff = lambda: setattr(window, 'ensured', True)

        CodingAgentIDE._open_project_tracker_change(window, "tmp_tracker_target.txt", "@@\n- old\n+ new")

        self.assertEqual(len(window.editor_panel.reloaded), 1)
        self.assertEqual(window.editor_panel.loaded, [os.path.join(os.getcwd(), "tmp_tracker_target.txt")])
        self.assertEqual(window.editor_panel.diffs, [(os.path.join(os.getcwd(), "tmp_tracker_target.txt"), "@@\n- old\n+ new", True)])
        self.assertTrue(window.ensured)

    def test_main_window_health_indicator_mentions_benchmark_model(self):
        label = type('FakeLabel', (), {
            '__init__': lambda self: setattr(self, 'text_value', '') or setattr(self, 'tooltip_value', '') or setattr(self, 'style_value', ''),
            'setText': lambda self, value: setattr(self, 'text_value', value),
            'setToolTip': lambda self, value: setattr(self, 'tooltip_value', value),
            'setStyleSheet': lambda self, value: setattr(self, 'style_value', value),
        })()
        window = type('FakeWindow', (), {
            '_status_openrouter': label,
            '_openrouter_health_indicator_style': staticmethod(CodingAgentIDE._openrouter_health_indicator_style),
        })()

        CodingAgentIDE._apply_openrouter_health_indicator(window, {
            'status': 'healthy',
            'message': 'OpenRouter ready: z-ai/glm-4.5-air:free',
            'recommended_full_model': '[OpenRouter] z-ai/glm-4.5-air:free',
        })

        self.assertIn('OpenRouter ready: z-ai/glm-4.5-air:free', label.text_value)
        self.assertIn('Benchmark: x-ai/grok-code-fast-1', label.text_value)
        self.assertIn(SettingsManager.DEFAULT_BENCHMARK_MODEL, label.tooltip_value)
        self.assertIn('[OpenRouter] z-ai/glm-4.5-air:free', label.tooltip_value)


if __name__ == '__main__':
    unittest.main()