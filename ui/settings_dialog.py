
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
)
from PySide6.QtCore import Qt
from core.settings import SettingsManager
from core.ai_client import AIClient


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings - Providers, Models & RAG")
        self.resize(900, 720)
        self.settings_manager = SettingsManager()

        # Load enabled models
        self.enabled_models = set(self.settings_manager.get_enabled_models())

        # PROVIDER CONFIG
        # Tuples of (ID, Display Name, API Key Name, Default Models)
        self.providers = [
            ("openai", "OpenAI", "openai", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]),
            (
                "google",
                "Google Gemini",
                "google",
                ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"],
            ),
            (
                "anthropic",
                "Anthropic",
                "anthropic",
                [
                    "claude-3-5-sonnet-20240620",
                    "claude-3-opus-20240229",
                    "claude-3-haiku-20240307",
                ],
            ),
            ("deepseek", "DeepSeek", "deepseek", ["deepseek-coder", "deepseek-chat"]),
            (
                "mistral",
                "Mistral AI",
                "mistral",
                ["mistral-large-latest", "mistral-small-latest"],
            ),
            ("xai", "xAI (Grok)", "xai", ["grok-beta"]),
            ("kimi", "Kimi (Moonshot)", "kimi", ["moonshot-v1-8k", "moonshot-v1-32k"]),
            ("zai", "Z.ai (Zhipu)", "zai", ["glm-4", "glm-3-turbo"]),
            ("openrouter", "OpenRouter", "openrouter", ["openrouter/auto"]),
            ("local", "Local LLM (Ollama)", "local", []),
        ]

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---------------------------
        # RAG / Vector engine section
        # ---------------------------
        rag_group = QGroupBox("RAG / Vector Engine")
        rag_layout = QHBoxLayout()

        left = QVBoxLayout()
        right = QVBoxLayout()
        rag_layout.addLayout(left, 2)
        rag_layout.addLayout(right, 1)
        rag_group.setLayout(rag_layout)

        self.rag_enabled = QCheckBox("Enable RAG (retrieve relevant code/files for the agent)")
        self.rag_enabled.setChecked(self.settings_manager.get_rag_enabled())
        left.addWidget(self.rag_enabled)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Vector Engine URL:"))
        self.vector_url = QLineEdit()
        self.vector_url.setText(self.settings_manager.get_vector_engine_url())
        self.vector_url.setPlaceholderText("http://127.0.0.1:8080")
        url_row.addWidget(self.vector_url, 1)
        left.addLayout(url_row)

        # Top-k
        topk_row = QHBoxLayout()
        topk_row.addWidget(QLabel("Top-K:"))
        self.rag_top_k = QSpinBox()
        self.rag_top_k.setRange(1, 50)
        self.rag_top_k.setValue(self.settings_manager.get_rag_top_k())
        self.rag_top_k.setFixedWidth(90)
        topk_row.addWidget(self.rag_top_k)
        topk_row.addStretch()
        left.addLayout(topk_row)

        # Min score
        minscore_row = QHBoxLayout()
        minscore_row.addWidget(QLabel("Min Score:"))
        self.rag_min_score = QDoubleSpinBox()
        self.rag_min_score.setRange(0.0, 1.0)
        self.rag_min_score.setSingleStep(0.05)
        self.rag_min_score.setDecimals(2)
        self.rag_min_score.setValue(self.settings_manager.get_rag_min_score())
        self.rag_min_score.setFixedWidth(90)
        minscore_row.addWidget(self.rag_min_score)
        minscore_row.addStretch()
        left.addLayout(minscore_row)

        # Embedding Model selection removed as it is now hardcoded to the native RIG system.

        # Quick hint + placeholder test button (we’ll wire a real ping once the client exists)
        hint = QLabel("Tip: Start the Go server first, then set URL here (e.g. http://127.0.0.1:8080).")
        hint.setStyleSheet("color: #9aa0a6;")
        left.addWidget(hint)

        self.rag_test_btn = QPushButton("Test Connection")
        self.rag_test_btn.setFixedWidth(150)
        self.rag_test_btn.clicked.connect(self.test_vector_engine_connection)
        right.addStretch()
        right.addWidget(self.rag_test_btn, alignment=Qt.AlignRight)

        layout.addWidget(rag_group)

        # ---------------------------
        # Provider selection (existing)
        # ---------------------------
        top_frame = QGroupBox("Select Provider")
        top_layout = QHBoxLayout()

        self.provider_combo = QComboBox()
        for _, name, _, _ in self.providers:
            self.provider_combo.addItem(name)
        self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)

        top_layout.addWidget(QLabel("Provider:"))
        top_layout.addWidget(self.provider_combo, 1)
        top_frame.setLayout(top_layout)
        layout.addWidget(top_frame)

        # Main config area (stacked)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.provider_ui = {}

        for p_id, p_name, p_key_name, p_defaults in self.providers:
            page = QWidget()
            self.setup_provider_page(page, p_id, p_name, p_key_name, p_defaults)
            self.stack.addWidget(page)

        # Global buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        self.save_btn.setStyleSheet(
            "background-color: #007fd4; color: white; font-weight: bold; padding: 6px 12px;"
        )
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

        # Initial selection
        if self.providers:
            self.on_provider_changed(0)

    def on_provider_changed(self, index):
        self.stack.setCurrentIndex(index)

    def setup_provider_page(self, page, p_id, p_name, p_key_name, p_defaults):
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # API Key / Config
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

        # Fetch Models button
        fetch_btn = QPushButton("Fetch Models")
        fetch_btn.setFixedWidth(120)
        fetch_btn.setStyleSheet("background-color: #2d2d2d; border: 1px solid #3e3e42;")
        fetch_btn.clicked.connect(lambda: self.fetch_models_for_provider(p_id))
        key_layout.addWidget(fetch_btn)

        key_group.setLayout(key_layout)
        layout.addWidget(key_group)

        # Models
        models_group = QGroupBox("Model Selection")
        models_layout = QVBoxLayout()

        lists_bg = QWidget()
        lists_layout = QHBoxLayout(lists_bg)
        lists_layout.setContentsMargins(0, 0, 0, 0)

        v1 = QVBoxLayout()
        v1.addWidget(QLabel("Available Models"))
        available_list = QListWidget()
        available_list.setSelectionMode(QListWidget.MultiSelection)
        available_list.setStyleSheet("background: #252526; border: 1px solid #3c3c3c;")
        v1.addWidget(available_list)
        lists_layout.addLayout(v1)

        btns = QVBoxLayout()
        btns.addStretch()
        btn_add = QPushButton("▶")
        btn_add.setFixedWidth(30)
        btn_add.clicked.connect(lambda: self.move_items(available_list, selected_list))
        btns.addWidget(btn_add)

        btn_rem = QPushButton("◀")
        btn_rem.setFixedWidth(30)
        btn_rem.clicked.connect(lambda: self.move_items(selected_list, available_list))
        btns.addWidget(btn_rem)
        btns.addStretch()
        lists_layout.addLayout(btns)

        v2 = QVBoxLayout()
        v2.addWidget(QLabel("Selected (Max 5)"))
        selected_list = QListWidget()
        selected_list.setSelectionMode(QListWidget.MultiSelection)
        selected_list.setStyleSheet("background: #252526; border: 1px solid #3c3c3c;")
        v2.addWidget(selected_list)
        lists_layout.addLayout(v2)

        models_layout.addWidget(lists_bg)
        models_group.setLayout(models_layout)
        layout.addWidget(models_group)

        # Store refs
        self.provider_ui[p_id] = {
            "key_input": key_input,
            "available": available_list,
            "selected": selected_list,
            "fetch_btn": fetch_btn,
        }

        self.populate_lists(p_id, p_name, p_defaults, available_list, selected_list)

    def populate_lists(self, p_id, p_name, p_defaults, available_list, selected_list):
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

    def move_items(self, source_list, target_list):
        for item in source_list.selectedItems():
            row = source_list.row(item)
            text = item.text()

            source_list.takeItem(row)
            target_list.addItem(text)

    def fetch_models_for_provider(self, p_id):
        ui = self.provider_ui[p_id]
        key = ui["key_input"].text().strip()

        if not key and p_id != "local":
            QMessageBox.warning(self, "Missing Key", f"Please enter an API Key for {p_id} first.")
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
                p_id, key, self.settings_manager.get_local_llm_url() if p_id == "local" else None
            )
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
                QMessageBox.information(self, "Fetch Complete", "No new models found.")
            else:
                QMessageBox.information(self, "Fetch Complete", f"Found {count} new models.")
        else:
            QMessageBox.warning(self, "Fetch Failed", "Could not fetch models. Check API Key or Network.")

    def test_vector_engine_connection(self):
        """
        Minimal connection test (no dependency on server implementing a dedicated /health endpoint).
        We just try a GET / (or /health) and accept any HTTP response as "reachable".
        """
        import urllib.request

        base = (self.vector_url.text() or "").strip()
        if not base:
            QMessageBox.warning(self, "Missing URL", "Please enter the Vector Engine URL first.")
            return

        # Try a couple of likely endpoints
        candidates = [base.rstrip("/") + "/health", base.rstrip("/") + "/"]
        last_err = None

        self.rag_test_btn.setEnabled(False)
        self.rag_test_btn.setText("Testing...")

        try:
            for url in candidates:
                try:
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        QMessageBox.information(
                            self,
                            "Vector Engine",
                            f"Connection OK.\n\nURL: {base}\nHTTP: {resp.status}",
                        )
                        return
                except Exception as e:
                    last_err = e

            QMessageBox.warning(
                self,
                "Vector Engine",
                f"Could not connect to:\n{base}\n\nError:\n{last_err}",
            )
        finally:
            self.rag_test_btn.setEnabled(True)
            self.rag_test_btn.setText("Test Connection")

    def save_settings(self):
        # Save RAG settings
        self.settings_manager.set_rag_enabled(self.rag_enabled.isChecked())
        self.settings_manager.set_vector_engine_url(self.vector_url.text().strip())
        self.settings_manager.set_rag_top_k(self.rag_top_k.value())
        self.settings_manager.set_rag_min_score(self.rag_min_score.value())
        # Embedding model is now hardcoded.

        # Save provider keys
        for p_id, _, p_key_name, _ in self.providers:
            input_val = self.provider_ui[p_id]["key_input"].text().strip()
            if p_id == "local":
                self.settings_manager.set_local_llm_url(input_val)
            else:
                self.settings_manager.set_api_key(p_key_name, input_val)

        # Collect all selected models from ALL tabs
        all_enabled = []
        for p_id in self.provider_ui:
            sel_list = self.provider_ui[p_id]["selected"]
            for i in range(sel_list.count()):
                all_enabled.append(sel_list.item(i).text())

        self.settings_manager.set_enabled_models(all_enabled)
        self.accept()
