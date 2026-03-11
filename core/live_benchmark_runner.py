import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Callable
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform.startswith("win"):
    _windows_font_dir = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
    if os.path.isdir(_windows_font_dir):
        os.environ.setdefault("QT_QPA_FONTDIR", _windows_font_dir)
_qt_logging_rules = os.environ.get("QT_LOGGING_RULES", "").strip()
if "qt.qpa.fonts.warning=false" not in _qt_logging_rules:
    os.environ["QT_LOGGING_RULES"] = ";".join(filter(None, [_qt_logging_rules, "qt.qpa.fonts.warning=false"]))

from PySide6.QtWidgets import QApplication

from core.agent_tools import get_project_root, set_project_root
from core.ai_client import AIClient
from core.code_parser import CodeParser
from core.live_benchmark_diagnostics import finalize_result, format_markdown_matrix, new_trace, observe_response, observe_tool_batch
from core.settings import SettingsManager
from ui.chat_panel import ChatPanel


NAVIGATION_COMMANDS = {"find_tests", "get_imports", "find_importers", "find_symbol", "find_references", "read_python_symbols"}
DEFAULT_BENCHMARK_OUTPUT_DIR = os.path.join("artifacts", "benchmarks")


class _NullRAGClient:
    def __init__(self, *args, **kwargs):
        pass

    def retrieve(self, *args, **kwargs):
        return []

    def format_context_block(self, *args, **kwargs):
        return ""

    def ingest_message(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class BenchmarkScenario:
    name: str
    prompt: str
    setup: Callable[[str], None]
    expected_changed_file: str | None = None
    require_navigation: bool = False


def _benchmark_test_provider_script(scenario: BenchmarkScenario) -> list[str]:
    if scenario.name == "blank_project_repair":
        return [
            '<execute_command command="python app.py" cwd="." />',
            '<edit_file path="app.py" start_line="1" end_line="2">message = "hello from maintained benchmark"\nprint(message)\n</edit_file>',
            '<execute_command command="python app.py" cwd="." />',
            '<read_file path="app.py" start_line="1" end_line="20" />',
            'I observed the runtime failure in app.py, fixed it, reran it successfully, and reread the final file.',
        ]
    if scenario.name == "navigation_report":
        return [
            '<find_symbol symbol="Worker.run" root_dir="." />',
            '<get_imports path="src/engine.py" include_external="false" />',
            '<find_importers target="src/engine.py" root_dir="." />',
            '<find_tests source_path="src/engine.py" />',
            '<write_file path="benchmark_report.md">Worker.run is defined in src/engine.py. It imports helper from core/helpers.py. consumer.py imports Worker, and tests/test_engine.py covers the flow.</write_file>',
            '<read_file path="benchmark_report.md" start_line="1" end_line="20" />',
            'I grounded the report with navigation tools and wrote benchmark_report.md based on src/engine.py, core/helpers.py, consumer.py, and tests/test_engine.py.',
        ]
    return list(AIClient.DEFAULT_TEST_PROVIDER_SCRIPT)


def _configure_benchmark_test_provider(model: str, scenario: BenchmarkScenario):
    provider, _model_id = AIClient.parse_model_selection(model)
    if provider != "test":
        return
    if getattr(AIClient, "_test_script", []):
        return
    AIClient.configure_test_provider(_benchmark_test_provider_script(scenario))


def _benchmark_model_is_temporarily_unhealthy(full_model: str, settings_manager: SettingsManager, now_ts: float | None = None) -> tuple[bool, dict | None]:
    provider, model_id = AIClient.parse_model_selection(full_model)
    if provider != "openrouter":
        return False, None
    snapshot = settings_manager.get_openrouter_health_state() or {}
    normalize = getattr(AIClient, "_normalize_openrouter_health_entry", None)
    entry = normalize(snapshot.get(model_id, {})) if callable(normalize) else snapshot.get(model_id, {})
    if not isinstance(entry, dict):
        return False, None
    now_ts = now_ts or time.time()
    status = str(entry.get("status", "unknown") or "unknown")
    try:
        cooldown_until = float(entry.get("cooldown_until", 0) or 0)
    except Exception:
        cooldown_until = 0.0
    if status in {"rate_limited", "policy_blocked", "request_failed"} and cooldown_until > now_ts:
        return True, {
            "model": full_model,
            "provider": provider,
            "model_id": model_id,
            "status": status,
            "cooldown_until": cooldown_until,
        }
    return False, None


def write_blank_project_fixture(_root: str):
    with open(os.path.join(_root, "app.py"), "w", encoding="utf-8") as f:
        f.write(
            "message = greeting\n"
            "print(message)\n"
        )


def write_navigation_fixture(root: str):
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    os.makedirs(os.path.join(root, "core"), exist_ok=True)
    os.makedirs(os.path.join(root, "tests"), exist_ok=True)
    with open(os.path.join(root, "src", "engine.py"), "w", encoding="utf-8") as f:
        f.write(
            "from core.helpers import helper\n\n"
            "class Worker:\n"
            "    def run(self):\n"
            "        return helper()\n"
        )
    with open(os.path.join(root, "core", "helpers.py"), "w", encoding="utf-8") as f:
        f.write("def helper():\n    return 'ok'\n")
    with open(os.path.join(root, "tests", "test_engine.py"), "w", encoding="utf-8") as f:
        f.write(
            "from src.engine import Worker\n\n"
            "def test_run_returns_helper_result():\n"
            "    assert Worker().run() == 'ok'\n"
        )
    with open(os.path.join(root, "consumer.py"), "w", encoding="utf-8") as f:
        f.write("from src.engine import Worker\n\nvalue = Worker().run()\n")


def default_scenarios() -> dict[str, BenchmarkScenario]:
    return {
        "blank_project_repair": BenchmarkScenario(
            name="blank_project_repair",
            prompt=(
                "This project already contains app.py with a deliberate runtime failure. Run python app.py, fix app.py, rerun it successfully, "
                "do one fresh read of app.py, and then summarize exactly what changed and what command proved it."
            ),
            setup=write_blank_project_fixture,
            expected_changed_file="app.py",
        ),
        "navigation_report": BenchmarkScenario(
            name="navigation_report",
            prompt=(
                "Use navigation tools to find where Worker.run is defined, what it imports, what imports it, and which tests cover it. "
                "Write a concise findings report to benchmark_report.md, read that report back, and then summarize exactly which files grounded your report."
            ),
            setup=write_navigation_fixture,
            expected_changed_file="benchmark_report.md",
            require_navigation=True,
        ),
    }


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


def _wait_until_idle(panel: ChatPanel, timeout_seconds: float) -> bool:
    app = _get_app()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        app.processEvents()
        if not panel.is_processing and getattr(panel, "ai_thread_obj", None) is None and getattr(panel, "tool_thread", None) is None:
            return True
        time.sleep(0.02)
    app.processEvents()
    return False


def _assistant_tools(text: str) -> list[dict]:
    tools = CodeParser.parse_tool_calls(text)
    if not tools:
        tools = ChatPanel._recover_fenced_tool_calls(text)
    return tools


def _result_from_panel(panel: ChatPanel, model: str, scenario: BenchmarkScenario, timed_out: bool, notifications: list[tuple[str, str]]):
    trace = new_trace(model)
    changed_files = []
    seen_files = set()
    final_response = ""
    navigation_used = any(cmd in NAVIGATION_COMMANDS for cmd in getattr(panel, "_run_tool_calls", []))
    for message in panel.messages:
        role = message.get("role")
        content = str(message.get("content", "") or "")
        if role == "assistant":
            observe_response(trace, content)
            tools = _assistant_tools(content)
            if tools:
                observe_tool_batch(trace, tools, "siege")
                navigation_used = navigation_used or any(call.get("cmd") in NAVIGATION_COMMANDS for call in tools)
            else:
                final_response = content
        elif role == "system":
            for path in ChatPanel._grounded_changed_files_from_summary(content):
                lowered = path.lower()
                if lowered not in seen_files:
                    seen_files.add(lowered)
                    changed_files.append(path)
    if not final_response:
        final_response = next((str(m.get("content", "") or "") for m in reversed(panel.messages) if m.get("role") == "assistant"), "")
    grounded_completion = not panel._summary_guard_violations(final_response)
    result = finalize_result(
        trace,
        guided_stage=panel._guided_takeoff_stage,
        autonomy_unlocked=panel._guided_autonomy_unlocked,
        no_progress_cycles=panel._guided_no_progress_cycles,
        changed_files=changed_files,
        final=final_response,
        grounded_completion=grounded_completion,
    )
    result["scenario"] = scenario.name
    result["notifications"] = [{"title": title, "message": message} for title, message in notifications]
    result["timed_out"] = timed_out
    result["navigation_used"] = navigation_used
    if timed_out:
        result["failure_code"] = "X1_RUN_TIMEOUT"
        result["failure_note"] = f"Scenario timed out after benchmark wait limit for {scenario.name}."
    elif scenario.expected_changed_file and scenario.expected_changed_file not in changed_files and not result.get("failure_code"):
        result["failure_code"] = "B1_EXPECTED_FILE_NOT_CHANGED"
        result["failure_note"] = f"Expected grounded changed file '{scenario.expected_changed_file}' was not observed."
    if scenario.require_navigation and not navigation_used and not result.get("failure_code"):
        result["failure_code"] = "N1_NO_NAVIGATION_EVIDENCE"
        result["failure_note"] = "Scenario required navigation tools, but no navigation-tool batch was observed."
    return result


def run_siege_benchmark(models: list[str], scenario_names: list[str] | None = None, timeout_seconds: float = 45.0):
    scenarios = default_scenarios()
    selected = [scenarios[name] for name in (scenario_names or list(scenarios.keys()))]
    results = []
    old_root = get_project_root()
    try:
        _get_app()
        for scenario in selected:
            for model in models:
                notifications = []
                tmpdir = tempfile.mkdtemp(prefix=f"vox_bench_{scenario.name}_")
                set_project_root(tmpdir)
                panel = None
                try:
                    _configure_benchmark_test_provider(model, scenario)
                    scenario.setup(tmpdir)
                    with patch.object(ChatPanel, "load_conversation", lambda self: None), \
                         patch.object(ChatPanel, "start_auto_indexing", lambda self: None), \
                         patch("ui.chat_panel.RAGClient", _NullRAGClient):
                        panel = ChatPanel()
                    panel.settings_manager.get_auto_approve_writes = MagicMock(return_value=True)
                    panel.settings_manager.get_auto_save_conversation = MagicMock(return_value=False)
                    panel.save_conversation = MagicMock()
                    panel.mode_combo.setCurrentText("Siege")
                    panel.model_combo.clear()
                    panel.model_combo.addItem(panel._display_model_name(model), model)
                    panel.model_combo.setCurrentIndex(0)
                    panel.notification_requested.connect(lambda title, message, sink=notifications: sink.append((title, message)))
                    panel.send_worker(scenario.prompt)
                    completed = _wait_until_idle(panel, timeout_seconds)
                    if not completed:
                        try:
                            panel.stop_current_action()
                        except Exception:
                            pass
                        _wait_until_idle(panel, 5.0)
                    result = _result_from_panel(panel, model, scenario, timed_out=not completed, notifications=notifications)
                    result["project_root"] = tmpdir
                    results.append(result)
                except Exception as exc:
                    results.append(
                        {
                            "model": model,
                            "scenario": scenario.name,
                            "pass": False,
                            "failure_code": "Z1_BENCHMARK_EXCEPTION",
                            "failure_note": f"Benchmark harness exception: {type(exc).__name__}: {exc}",
                            "timed_out": False,
                            "guided_stage": getattr(panel, "_guided_takeoff_stage", 0) if panel else 0,
                            "guided_autonomy_unlocked": getattr(panel, "_guided_autonomy_unlocked", False) if panel else False,
                            "changed_files": [],
                            "final_excerpt": "",
                            "furthest_stage_code": "Z0_EXCEPTION",
                            "notifications": [{"title": title, "message": message} for title, message in notifications],
                            "project_root": tmpdir,
                        }
                    )
                finally:
                    if panel is not None:
                        try:
                            panel._shutdown_background_threads()
                        except Exception:
                            pass
                        try:
                            panel.close()
                        except Exception:
                            pass
                    _get_app().processEvents()
    finally:
        set_project_root(old_root)
        AIClient.clear_test_provider()
    return results


def enabled_models(include_unhealthy: bool = False) -> list[str]:
    settings_manager = SettingsManager()
    models = [str(model).strip() for model in (settings_manager.get_enabled_models() or []) if str(model).strip()]
    if include_unhealthy:
        enabled_models.last_skipped = []
        return models
    filtered = []
    skipped = []
    now_ts = time.time()
    for model in models:
        unhealthy, detail = _benchmark_model_is_temporarily_unhealthy(model, settings_manager, now_ts)
        if unhealthy:
            skipped.append(detail)
            continue
        filtered.append(model)
    enabled_models.last_skipped = skipped
    return filtered


enabled_models.last_skipped = []


def resolve_output_artifact_path(requested_path: str | None, default_name: str) -> str:
    if requested_path:
        return requested_path
    return os.path.join(DEFAULT_BENCHMARK_OUTPUT_DIR, default_name)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run maintained live Siege benchmarks.")
    parser.add_argument("--model", action="append", dest="models", help="Full model identifier. Repeat for multiple models.")
    parser.add_argument("--scenario", action="append", dest="scenarios", choices=sorted(default_scenarios().keys()), help="Scenario name. Repeat to limit the run.")
    parser.add_argument("--timeout", type=float, default=45.0, help="Per-run timeout in seconds.")
    parser.add_argument("--output-json", help="Where to write JSON results.")
    parser.add_argument("--output-markdown", help="Where to write the markdown matrix.")
    parser.add_argument("--include-unhealthy", action="store_true", help="Include OpenRouter models that are currently on an active health cooldown.")
    args = parser.parse_args(argv)

    models = args.models or enabled_models(include_unhealthy=args.include_unhealthy)
    if not models:
        print("No enabled models were found and no --model values were provided.")
        return 2
    if not args.models and not args.include_unhealthy:
        skipped = list(getattr(enabled_models, "last_skipped", []) or [])
        if skipped:
            print("Skipping temporarily unhealthy OpenRouter models:")
            for item in skipped:
                print(f"- {item.get('model')}: {item.get('status')}")
            print()

    results = run_siege_benchmark(models, scenario_names=args.scenarios, timeout_seconds=args.timeout)
    markdown = format_markdown_matrix(results)
    output_json = resolve_output_artifact_path(args.output_json, "siege_benchmark_results.json")
    output_markdown = resolve_output_artifact_path(args.output_markdown, "siege_benchmark_results.md")
    output_json_dir = os.path.dirname(output_json)
    output_markdown_dir = os.path.dirname(output_markdown)
    if output_json_dir:
        os.makedirs(output_json_dir, exist_ok=True)
    if output_markdown_dir:
        os.makedirs(output_markdown_dir, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    with open(output_markdown, "w", encoding="utf-8") as f:
        f.write(markdown + "\n")
    print(markdown)
    print(f"\nWrote {output_json} and {output_markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())