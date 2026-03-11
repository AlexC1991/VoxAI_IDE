from PySide6.QtCore import Qt

from core.ai_client import AIClient
from core.settings import SettingsManager


def _short_model_name(full: str) -> str:
    """Turn '[OpenRouter] anthropic/claude-opus-4-20250514' into 'claude-opus-4'."""
    name = full
    if "]" in name:
        name = name.split("]", 1)[1].strip()
    if "/" in name:
        name = name.rsplit("/", 1)[1]
    import re as _re
    return _re.sub(r'-\d{8,}$', '', name)


def _recommended_benchmark_model() -> str:
    return SettingsManager.DEFAULT_BENCHMARK_MODEL


def _display_model_name(self, full: str) -> str:
    entry = AIClient.get_model_picker_entry(full, self.settings_manager)
    return entry.get("label") or self._short_model_name(full)


def _refresh_model_combo_tooltip(self):
    recommended = self._recommended_benchmark_model()
    if not recommended:
        self.model_combo.setToolTip("")
        return
    recommended_short = self._short_model_name(recommended)
    current_full = self._get_full_model_name()
    if current_full == recommended:
        self.model_combo.setToolTip(f"Recommended benchmark model selected: {recommended_short}")
    else:
        self.model_combo.setToolTip(f"Recommended benchmark model: {recommended_short}")


def refresh_models(self):
    current_full = self._get_full_model_name()
    if not current_full:
        current_full = (self.settings_manager.get_selected_model() or "").strip()

    models = self.settings_manager.get_enabled_models() or []
    models = [m for m in models if isinstance(m, str) and m.strip()]
    visible_models = []
    hidden_current = None
    for model_name in models:
        entry = AIClient.get_model_picker_entry(model_name, self.settings_manager)
        if entry.get("show_in_picker"):
            visible_models.append((model_name, entry))
        elif model_name == current_full:
            hidden_current = model_name

    if current_full and current_full not in models:
        entry = AIClient.get_model_picker_entry(current_full, self.settings_manager)
        if entry.get("show_in_picker"):
            visible_models.insert(0, (current_full, entry))
        else:
            hidden_current = current_full

    if not visible_models and hidden_current:
        entry = AIClient.get_model_picker_entry(hidden_current, self.settings_manager)
        visible_models.append((hidden_current, entry))

    self.model_combo.blockSignals(True)
    self.model_combo.clear()
    for model_name, entry in visible_models:
        self.model_combo.addItem(entry.get("label") or self._display_model_name(model_name), model_name)
        index = self.model_combo.count() - 1
        if entry.get("tooltip"):
            self.model_combo.setItemData(index, entry["tooltip"], Qt.ToolTipRole)
    self.model_combo.blockSignals(False)

    for i in range(self.model_combo.count()):
        if self.model_combo.itemData(i) == current_full:
            self.model_combo.setCurrentIndex(i)
            break
    else:
        if self.model_combo.count() > 0:
            self.model_combo.setCurrentIndex(0)
            self.settings_manager.set_selected_model(
                self.model_combo.currentData() or self.model_combo.currentText())
    self._refresh_model_combo_tooltip()


def _prepare_selected_model_for_send(self, *, run_probe=True):
    current_full = self._get_full_model_name()
    if not current_full:
        current_full = (self.settings_manager.get_selected_model() or "").strip()

    plan = AIClient.prepare_model_for_request(
        current_full,
        settings_manager=self.settings_manager,
        run_probe=run_probe,
    )
    effective_model = (plan.get("effective_model") or current_full or "").strip()
    blocked_reason = (plan.get("blocked_reason") or "").strip()
    note = (plan.get("note") or "").strip()

    if effective_model:
        self.settings_manager.set_selected_model(effective_model)
    if effective_model and effective_model != current_full:
        self.refresh_models()

    if note:
        self.notification_requested.emit("Model Safety Gate", note)

    return not blocked_reason, blocked_reason


def _get_full_model_name(self) -> str:
    """Return the full model identifier from item data, falling back to display text."""
    if self.model_combo.count() == 0:
        return ""
    return (self.model_combo.currentData() or self.model_combo.currentText() or "").strip()


def _handle_ai_model_selected(self, full_model_name: str, note: str):
    if full_model_name:
        self.settings_manager.set_selected_model(full_model_name)
        self.refresh_models()
    if note:
        self.notification_requested.emit("OpenRouter Preflight", note)


__all__ = [name for name in globals() if name.startswith("_") or name == "refresh_models"]