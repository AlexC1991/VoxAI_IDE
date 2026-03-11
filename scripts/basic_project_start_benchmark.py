import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
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
from core.summary_guard import SummaryGuard
from ui.chat_panel import ChatPanel

PROMPT = (
    "This folder is empty. Start a very small new Python project here. "
    "Create only the minimum files needed for a basic runnable CLI starter: "
    "app.py that prints a short greeting, plus a short README.md with run instructions. "
    "Then validate it by running python app.py. Keep the project tiny and grounded."
)
DEFAULT_OUTPUT_DIR = Path("artifacts") / "benchmarks"


class _NullRAGClient:
    def retrieve(self, *args, **kwargs):
        return []

    def format_context_block(self, *args, **kwargs):
        return ""

    def ingest_message(self, *args, **kwargs):
        return None


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


def sanitize_model_slug(model: str) -> str:
    cleaned = []
    previous_underscore = False
    for ch in str(model or "").lower():
        if ch.isalnum():
            cleaned.append(ch)
            previous_underscore = False
            continue
        if not previous_underscore:
            cleaned.append("_")
            previous_underscore = True
    return "".join(cleaned).strip("_") or "benchmark_model"


def resolve_output_path(requested_output: str | None, model: str) -> Path:
    if requested_output:
        return Path(requested_output)
    slug = sanitize_model_slug(model)
    return DEFAULT_OUTPUT_DIR / f"basic_project_start_{slug}.json"


def last_assistant_message(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "assistant":
            return str(message.get("content", ""))
    return ""


def last_user_ready_assistant_message(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") != "assistant":
            continue
        content = str(message.get("content", ""))
        if SummaryGuard.user_ready_final_response(content):
            return content
    return ""


def evaluate_run_outcome(completed: bool, files: list[str], run_check: dict | None, messages: list[dict]) -> dict:
    raw_final = last_assistant_message(messages)
    user_ready_final = last_user_ready_assistant_message(messages)
    final_is_user_ready = SummaryGuard.user_ready_final_response(raw_final)
    quality_issue = None if final_is_user_ready else 'non_user_ready_final_message'
    full_success = bool(
        completed and 'app.py' in files and 'README.md' in files and run_check and run_check['return_code'] == 0 and final_is_user_ready
    )
    return {
        'final_message': raw_final,
        'final_user_ready_message': user_ready_final,
        'final_message_user_ready': final_is_user_ready,
        'quality_issue': quality_issue,
        'full_requested_success': full_success,
    }


def wait_until(predicate, timeout=300.0):
    app = _get_app()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def run_once(model: str) -> dict:
    original_root = get_project_root()
    project_dir = tempfile.mkdtemp(prefix="vox_basic_project_")
    token_events = []
    started = time.time()
    panel = None
    try:
        _get_app()
        set_project_root(project_dir)
        with patch.object(ChatPanel, "load_conversation", lambda self: None), \
             patch.object(ChatPanel, "start_auto_indexing", lambda self: None), \
             patch("ui.chat_panel.RAGClient", _NullRAGClient):
            panel = ChatPanel()
        panel.settings_manager.get_auto_approve_writes = lambda: True
        panel.settings_manager.get_auto_save_conversation = lambda: False
        panel.settings_manager.get_advanced_agent_tools_enabled = lambda: False
        panel.settings_manager.get_web_search_enabled = lambda: False
        panel.save_conversation = MagicMock()
        panel.mode_combo.setCurrentText("Siege")
        panel.model_combo.clear()
        panel.model_combo.addItem(model.split('] ', 1)[-1], model)
        panel.model_combo.setCurrentIndex(0)
        panel.on_model_changed(model)
        original_handle_ai_usage = panel.handle_ai_usage

        def capture_usage(usage):
            if usage:
                token_events.append({k: int(usage.get(k, 0) or 0) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')})
            return original_handle_ai_usage(usage)

        panel.handle_ai_usage = capture_usage
        panel.send_worker(PROMPT)
        completed = wait_until(lambda: not panel.is_processing and getattr(panel, 'ai_thread_obj', None) is None and getattr(panel, 'tool_thread', None) is None)
        files = sorted(str(p.relative_to(project_dir)).replace('\\', '/') for p in Path(project_dir).rglob('*') if p.is_file())
        run_check = None
        if Path(project_dir, 'app.py').exists():
            proc = subprocess.run([sys.executable, 'app.py'], cwd=project_dir, capture_output=True, text=True, timeout=30)
            run_check = {'return_code': proc.returncode, 'stdout': proc.stdout.strip(), 'stderr': proc.stderr.strip()}
        outcome = evaluate_run_outcome(completed, files, run_check, panel.messages)
        return {
            'completed': completed,
            'elapsed_seconds': round(time.time() - started, 2),
            'files_created': files,
            'assistant_messages': len([m for m in panel.messages if m.get('role') == 'assistant']),
            'token_events': token_events,
            'estimated_prompt_tokens_total': sum(e['prompt_tokens'] for e in token_events),
            'estimated_completion_tokens_total': sum(e['completion_tokens'] for e in token_events),
            'estimated_total_tokens': sum(e['total_tokens'] for e in token_events),
            'run_check': run_check,
            **outcome,
        }
    finally:
        if panel is not None:
            try:
                panel.close()
            except Exception:
                pass
            _get_app().processEvents()
        set_project_root(original_root)
        shutil.rmtree(project_dir, ignore_errors=True)


def summarize(model: str, runs: list[dict]) -> dict:
    totals = [int(r['estimated_total_tokens']) for r in runs]
    elapsed = [float(r['elapsed_seconds']) for r in runs]
    return {
        'model': model,
        'prompt': PROMPT,
        'runs': runs,
        'mean_total_tokens': round(statistics.mean(totals), 2) if totals else 0,
        'min_total_tokens': min(totals) if totals else 0,
        'max_total_tokens': max(totals) if totals else 0,
        'mean_elapsed_seconds': round(statistics.mean(elapsed), 2) if elapsed else 0,
        'full_requested_successes': sum(1 for r in runs if r['full_requested_success']),
        'completed_runs': sum(1 for r in runs if r['completed']),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model', nargs='+')
    parser.add_argument('--repetitions', type=int, default=1)
    parser.add_argument('--output')
    args = parser.parse_args()
    model = ' '.join(args.model)
    runs = [run_once(model) for _ in range(max(1, args.repetitions))]
    result = summarize(model, runs)
    output_path = resolve_output_path(args.output, model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    print(f"\nSaved benchmark output to: {output_path}")


if __name__ == '__main__':
    main()

