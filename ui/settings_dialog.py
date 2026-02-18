
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QGroupBox,
    QListWidget,
    QComboBox,
    QStackedWidget,
    QWidget,
    QMessageBox,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QGridLayout,
    QTabWidget,
)
from PySide6.QtCore import Qt
from core.settings import SettingsManager
from core.ai_client import AIClient


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(920, 700)
        self.settings_manager = SettingsManager()

        self.enabled_models = set(self.settings_manager.get_enabled_models())

        self.providers = [
            ("openai", "OpenAI", "openai", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]),
            ("google", "Google Gemini", "google",
             ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"]),
            ("anthropic", "Anthropic", "anthropic",
             ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-haiku-20240307"]),
            ("deepseek", "DeepSeek", "deepseek", ["deepseek-coder", "deepseek-chat"]),
            ("mistral", "Mistral AI", "mistral",
             ["mistral-large-latest", "mistral-small-latest"]),
            ("xai", "xAI (Grok)", "xai", ["grok-beta"]),
            ("kimi", "Kimi (Moonshot)", "kimi", ["moonshot-v1-8k", "moonshot-v1-32k"]),
            ("zai", "Z.ai (Zhipu)", "zai", ["glm-4", "glm-3-turbo"]),
            ("openrouter", "OpenRouter", "openrouter", ["openrouter/auto"]),
        ]

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # ── Tabs ──────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3f3f46;
                background: #1e1e1e;
            }
            QTabBar::tab {
                background: #27272a; color: #a1a1aa;
                padding: 8px 18px; border: 1px solid #3f3f46;
                border-bottom: none; margin-right: 2px;
                font-family: 'Consolas', monospace; font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #1e1e1e; color: #00f3ff;
                border-bottom: 2px solid #00f3ff;
            }
            QTabBar::tab:hover { color: #e4e4e7; }
        """)
        root_layout.addWidget(self.tabs, 1)

        # Tab 1 — Providers & Models (needs the most vertical space)
        self.tabs.addTab(self._build_providers_tab(), "Providers && Models")

        # Tab 2 — Agent & RAG
        self.tabs.addTab(self._build_agent_tab(), "Agent && RAG")

        # Tab 3 — Appearance & Local Models
        self.tabs.addTab(self._build_appearance_tab(), "Appearance")

        # ── Save / Cancel ─────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        self.save_btn.setStyleSheet(
            "background-color: #007fd4; color: white; font-weight: bold; "
            "padding: 8px 20px; border-radius: 4px;")
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet("padding: 8px 20px;")
        btn_layout.addWidget(self.cancel_btn)

        root_layout.addLayout(btn_layout)

    # ==================================================================
    # Tab 1 — Providers & Models
    # ==================================================================
    def _build_providers_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Provider selector
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Provider:"))
        self.provider_combo = QComboBox()
        for _, name, _, _ in self.providers:
            self.provider_combo.addItem(name)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_combo.setMinimumWidth(200)
        selector_row.addWidget(self.provider_combo, 1)
        layout.addLayout(selector_row)

        # Stacked pages — one per provider
        self.stack = QStackedWidget()
        self.provider_ui = {}

        for p_id, p_name, p_key_name, p_defaults in self.providers:
            ppage = QWidget()
            self._setup_provider_page(ppage, p_id, p_name, p_key_name, p_defaults)
            self.stack.addWidget(ppage)

        layout.addWidget(self.stack, 1)

        if self.providers:
            self._on_provider_changed(0)

        return page

    def _on_provider_changed(self, index):
        self.stack.setCurrentIndex(index)

    def _setup_provider_page(self, page, p_id, p_name, p_key_name, p_defaults):
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        # API Key row
        key_group = QGroupBox("Configuration")
        key_layout = QHBoxLayout()

        lbl_text = "API Key:" if p_id != "local" else "Server URL:"
        lbl = QLabel(lbl_text)
        lbl.setFixedWidth(80)

        key_input = QLineEdit()
        key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        if p_id == "local":
            key_input.setEchoMode(QLineEdit.Normal)
            key_input.setText(self.settings_manager.get_local_llm_url())
            key_input.setPlaceholderText("http://localhost:11434/v1")
        else:
            key_input.setText(self.settings_manager.get_api_key(p_key_name))
            key_input.setPlaceholderText(f"Enter {p_name} API Key")

        key_layout.addWidget(lbl)
        key_layout.addWidget(key_input)

        fetch_btn = QPushButton("Fetch Models")
        fetch_btn.setFixedWidth(120)
        fetch_btn.setStyleSheet("background-color: #2d2d2d; border: 1px solid #3e3e42;")
        fetch_btn.clicked.connect(lambda: self._fetch_models_for_provider(p_id))
        key_layout.addWidget(fetch_btn)

        key_group.setLayout(key_layout)
        layout.addWidget(key_group)

        # Model selection — Available / Selected lists
        models_group = QGroupBox("Model Selection")
        models_layout = QVBoxLayout()

        lists_widget = QWidget()
        lists_layout = QHBoxLayout(lists_widget)
        lists_layout.setContentsMargins(0, 0, 0, 0)

        v1 = QVBoxLayout()
        v1.addWidget(QLabel("Available Models"))
        available_list = QListWidget()
        available_list.setSelectionMode(QListWidget.MultiSelection)
        available_list.setMinimumHeight(180)
        available_list.setStyleSheet("background: #252526; border: 1px solid #3c3c3c;")
        v1.addWidget(available_list)
        lists_layout.addLayout(v1)

        btns = QVBoxLayout()
        btns.addStretch()
        btn_add = QPushButton("▶")
        btn_add.setFixedWidth(30)
        btn_add.clicked.connect(lambda: self._move_items(available_list, selected_list))
        btns.addWidget(btn_add)
        btn_rem = QPushButton("◀")
        btn_rem.setFixedWidth(30)
        btn_rem.clicked.connect(lambda: self._move_items(selected_list, available_list))
        btns.addWidget(btn_rem)
        btns.addStretch()
        lists_layout.addLayout(btns)

        v2 = QVBoxLayout()
        v2.addWidget(QLabel("Selected (Active)"))
        selected_list = QListWidget()
        selected_list.setSelectionMode(QListWidget.MultiSelection)
        selected_list.setMinimumHeight(180)
        selected_list.setStyleSheet("background: #252526; border: 1px solid #3c3c3c;")
        v2.addWidget(selected_list)
        lists_layout.addLayout(v2)

        models_layout.addWidget(lists_widget)
        models_group.setLayout(models_layout)
        layout.addWidget(models_group, 1)

        self.provider_ui[p_id] = {
            "key_input": key_input,
            "available": available_list,
            "selected": selected_list,
            "fetch_btn": fetch_btn,
        }

        self._populate_lists(p_id, p_name, p_defaults, available_list, selected_list)

    # ==================================================================
    # Tab 2 — Agent & RAG
    # ==================================================================
    def _build_agent_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── Agent Behavior ──
        agent_group = QGroupBox("Agent Behavior")
        agent_layout = QVBoxLayout()
        agent_layout.setSpacing(8)

        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("Max History Tokens:"))
        self.token_budget = QSpinBox()
        self.token_budget.setRange(4000, 128000)
        self.token_budget.setSingleStep(1000)
        self.token_budget.setValue(self.settings_manager.get_max_history_tokens())
        self.token_budget.setFixedWidth(100)
        self.token_budget.setToolTip(
            "Maximum tokens of conversation history sent to the AI.\n"
            "Higher = more context but slower/costlier.\n"
            "Default: 24000 (~75% of a 32k window).")
        token_row.addWidget(self.token_budget)
        token_row.addStretch()
        agent_layout.addLayout(token_row)

        self.auto_approve_cb = QCheckBox(
            "Auto-approve file writes (skip Accept/Reject dialog in Phased mode)")
        self.auto_approve_cb.setChecked(self.settings_manager.get_auto_approve_writes())
        self.auto_approve_cb.setToolTip(
            "When disabled, the AI shows a diff and asks before writing files.")
        agent_layout.addWidget(self.auto_approve_cb)

        self.auto_save_cb = QCheckBox("Auto-save conversations to .vox/conversation.json")
        self.auto_save_cb.setChecked(self.settings_manager.get_auto_save_conversation())
        agent_layout.addWidget(self.auto_save_cb)

        self.web_search_cb = QCheckBox("Enable web search tool (requires internet)")
        self.web_search_cb.setChecked(self.settings_manager.get_web_search_enabled())
        agent_layout.addWidget(self.web_search_cb)

        agent_group.setLayout(agent_layout)
        layout.addWidget(agent_group)

        # ── RAG / Vector Engine ──
        rag_group = QGroupBox("RAG / Vector Engine")
        rag_layout = QVBoxLayout()
        rag_layout.setSpacing(8)

        self.rag_enabled = QCheckBox(
            "Enable RAG (retrieve relevant code/files for the agent)")
        self.rag_enabled.setChecked(self.settings_manager.get_rag_enabled())
        self.rag_enabled.setToolTip(
            "If enabled, the AI will search your project for code relevant to your query.")
        rag_layout.addWidget(self.rag_enabled)

        topk_row = QHBoxLayout()
        topk_row.addWidget(QLabel("Top-K:"))
        self.rag_top_k = QSpinBox()
        self.rag_top_k.setRange(1, 50)
        self.rag_top_k.setValue(self.settings_manager.get_rag_top_k())
        self.rag_top_k.setFixedWidth(90)
        self.rag_top_k.setToolTip(
            "Values: 1-50 (Default: 5). Controls how many 'memory chunks' the AI retrieves.\n"
            "Higher = More context but slower.\n"
            "Lower = Faster but might miss details.")
        topk_row.addWidget(self.rag_top_k)
        topk_row.addStretch()
        rag_layout.addLayout(topk_row)

        minscore_row = QHBoxLayout()
        minscore_row.addWidget(QLabel("Min Score:"))
        self.rag_min_score = QDoubleSpinBox()
        self.rag_min_score.setRange(0.0, 1.0)
        self.rag_min_score.setSingleStep(0.05)
        self.rag_min_score.setDecimals(2)
        self.rag_min_score.setValue(self.settings_manager.get_rag_min_score())
        self.rag_min_score.setFixedWidth(90)
        self.rag_min_score.setToolTip(
            "Values: 0.00-1.00 (Default: 0.00). Strictness filter for memory retrieval.\n"
            "0.00 = Loose (Show best matches even if weak).\n"
            "0.50+ = Strict (Only show very strong matches).")
        minscore_row.addWidget(self.rag_min_score)
        minscore_row.addStretch()
        rag_layout.addLayout(minscore_row)

        rag_group.setLayout(rag_layout)
        layout.addWidget(rag_group)

        layout.addStretch()
        return page

    # ==================================================================
    # Tab 3 — Appearance & Local Models
    # ==================================================================
    def _build_appearance_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── Chat Colors ──
        color_group = QGroupBox("Chat Colors")
        color_layout = QGridLayout()
        color_layout.setSpacing(10)
        color_layout.setContentsMargins(15, 15, 15, 15)

        self.user_color_input = QLineEdit()
        self.user_color_input.setText(self.settings_manager.get_chat_user_color())
        self.user_color_input.setPlaceholderText("#d4d4d8")
        self.user_color_input.setFixedWidth(90)
        btn_pick_user = QPushButton("Pick")
        btn_pick_user.clicked.connect(lambda: self._pick_color(self.user_color_input))
        color_layout.addWidget(QLabel("User Text:"), 0, 0)
        color_layout.addWidget(self.user_color_input, 0, 1)
        color_layout.addWidget(btn_pick_user, 0, 2)

        self.ai_color_input = QLineEdit()
        self.ai_color_input.setText(self.settings_manager.get_chat_ai_color())
        self.ai_color_input.setPlaceholderText("#ff9900")
        self.ai_color_input.setFixedWidth(90)
        btn_pick_ai = QPushButton("Pick")
        btn_pick_ai.clicked.connect(lambda: self._pick_color(self.ai_color_input))
        color_layout.addWidget(QLabel("AI Text:"), 1, 0)
        color_layout.addWidget(self.ai_color_input, 1, 1)
        color_layout.addWidget(btn_pick_ai, 1, 2)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # ── Local GGUF Models ──
        local_group = QGroupBox("Local GGUF Models")
        local_layout = QVBoxLayout()
        local_layout.addWidget(
            QLabel("Manage local .gguf models for offline inference:"))
        self.model_mgr_btn = QPushButton("Open Model Manager…")
        self.model_mgr_btn.setStyleSheet(
            "background-color: #27272a; border: 1px solid #3f3f46; "
            "padding: 8px 16px; border-radius: 4px;")
        self.model_mgr_btn.clicked.connect(self._open_model_manager)
        local_layout.addWidget(self.model_mgr_btn)
        local_group.setLayout(local_layout)
        layout.addWidget(local_group)

        layout.addStretch()
        return page

    # ==================================================================
    # Helpers
    # ==================================================================
    def _open_model_manager(self):
        from ui.model_manager import ModelManagerDialog
        dlg = ModelManagerDialog(self)
        dlg.model_selected.connect(self._on_model_selected)
        dlg.exec()

    def _on_model_selected(self, filename):
        model_str = f"[Local] {filename}"
        from core.settings import SettingsManager
        SettingsManager().set_selected_model(model_str)

    def _pick_color(self, line_edit):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor()
        if c.isValid():
            line_edit.setText(c.name())

    def _populate_lists(self, p_id, p_name, p_defaults, available_list, selected_list):
        available_list.clear()
        selected_list.clear()

        prefix = f"[{p_name}] "

        provider_enabled = []
        for em in self.enabled_models:
            if em.startswith(prefix):
                provider_enabled.append(em)

        for em in provider_enabled:
            selected_list.addItem(em)

        for code in p_defaults:
            full = f"{prefix}{code}"
            if full not in self.enabled_models:
                available_list.addItem(full)

    def _move_items(self, source_list, target_list):
        for item in source_list.selectedItems():
            row = source_list.row(item)
            text = item.text()
            source_list.takeItem(row)
            target_list.addItem(text)

    def _fetch_models_for_provider(self, p_id):
        ui = self.provider_ui[p_id]
        key = ui["key_input"].text().strip()

        if not key and p_id != "local":
            QMessageBox.warning(
                self, "Missing Key",
                f"Please enter an API Key for {p_id} first.")
            return

        btn = ui["fetch_btn"]
        btn.setText("Fetching...")
        btn.setEnabled(False)

        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

        try:
            if p_id == "openrouter":
                self.settings_manager.set_openrouter_key(key)
            else:
                self.settings_manager.set_api_key(p_id, key)

            models = AIClient.fetch_models(
                p_id, key,
                self.settings_manager.get_local_llm_url() if p_id == "local" else None)
        except Exception as e:
            models = []
            print(f"Fetch error: {e}")

        QApplication.restoreOverrideCursor()
        btn.setText("Fetch Models")
        btn.setEnabled(True)

        if models:
            avail_list = ui["available"]
            sel_list = ui["selected"]

            p_name = [x[1] for x in self.providers if x[0] == p_id][0]
            prefix = f"[{p_name}] "

            existing = set()
            for i in range(avail_list.count()):
                existing.add(avail_list.item(i).text())
            for i in range(sel_list.count()):
                existing.add(sel_list.item(i).text())

            count = 0
            for m in models:
                full = f"{prefix}{m}"
                if full not in existing:
                    avail_list.addItem(full)
                    count += 1

            if count == 0:
                QMessageBox.information(
                    self, "Fetch Complete", "No new models found.")
            else:
                QMessageBox.information(
                    self, "Fetch Complete", f"Found {count} new models.")
        else:
            QMessageBox.warning(
                self, "Fetch Failed",
                "Could not fetch models. Check API Key or Network.")

    def save_settings(self):
        # RAG
        self.settings_manager.set_rag_enabled(self.rag_enabled.isChecked())
        self.settings_manager.set_rag_top_k(self.rag_top_k.value())
        self.settings_manager.set_rag_min_score(self.rag_min_score.value())

        # Agent Behavior
        self.settings_manager.set_max_history_tokens(self.token_budget.value())
        self.settings_manager.set_auto_approve_writes(self.auto_approve_cb.isChecked())
        self.settings_manager.set_auto_save_conversation(self.auto_save_cb.isChecked())
        self.settings_manager.set_web_search_enabled(self.web_search_cb.isChecked())

        # Appearance
        self.settings_manager.set_chat_user_color(self.user_color_input.text().strip())
        self.settings_manager.set_chat_ai_color(self.ai_color_input.text().strip())

        # Provider keys
        for p_id, _, p_key_name, _ in self.providers:
            input_val = self.provider_ui[p_id]["key_input"].text().strip()
            if p_id == "local":
                self.settings_manager.set_local_llm_url(input_val)
            else:
                self.settings_manager.set_api_key(p_key_name, input_val)

        # Collect all selected models from ALL provider tabs
        all_enabled = []
        for p_id in self.provider_ui:
            sel_list = self.provider_ui[p_id]["selected"]
            for i in range(sel_list.count()):
                all_enabled.append(sel_list.item(i).text())

        self.settings_manager.set_enabled_models(all_enabled)
        self.accept()
