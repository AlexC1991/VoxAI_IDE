from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit, 
                             QPushButton, QHBoxLayout, QFormLayout, QGroupBox, 
                             QListWidget, QListWidgetItem, QComboBox, QStackedWidget, QWidget, QMessageBox)
from PySide6.QtCore import Qt, QSize
from core.settings import SettingsManager
from core.ai_client import AIClient

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings - Providers & Models")
        self.resize(900, 650) 
        self.settings_manager = SettingsManager()
        
        # Load enabled models
        self.enabled_models = set(self.settings_manager.get_enabled_models())
        
        # PROVIDER CONFIG
        # Tuples of (ID, Display Name, API Key Name, Default Models)
        self.providers = [
            ("openai", "OpenAI", "openai", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]),
            ("google", "Google Gemini", "google", ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"]),
            ("anthropic", "Anthropic", "anthropic", ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-haiku-20240307"]),
            ("deepseek", "DeepSeek", "deepseek", ["deepseek-coder", "deepseek-chat"]),
            ("mistral", "Mistral AI", "mistral", ["mistral-large-latest", "mistral-small-latest"]),
            ("xai", "xAI (Grok)", "xai", ["grok-beta"]),
            ("kimi", "Kimi (Moonshot)", "kimi", ["moonshot-v1-8k", "moonshot-v1-32k"]),
            ("zai", "Z.ai (Zhipu)", "zai", ["glm-4", "glm-3-turbo"]),
            ("openrouter", "OpenRouter", "openrouter", ["openrouter/auto"]), 
            ("local", "Local LLM (Ollama)", "local", [])
        ]

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # 1. Top Section: Provider Selection
        top_frame = QGroupBox("Select Provider")
        top_layout = QHBoxLayout()
        
        self.provider_combo = QComboBox()
        for _, name, _, _ in self.providers:
            self.provider_combo.addItem(name)
        self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)
        
        top_layout.addWidget(QLabel("Provider:"))
        top_layout.addWidget(self.provider_combo, 1) # Stretch
        top_frame.setLayout(top_layout)
        layout.addWidget(top_frame)
        
        # 2. Main Config Area (Stacked)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        
        self.provider_ui = {} 
        
        for p_id, p_name, p_key_name, p_defaults in self.providers:
            page = QWidget()
            self.setup_provider_page(page, p_id, p_name, p_key_name, p_defaults)
            self.stack.addWidget(page)
            
        # 3. Global Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        self.save_btn.setStyleSheet("background-color: #007fd4; color: white; font-weight: bold; padding: 6px 12px;")
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
        
        # --- API Key / Config ---
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
        
        # FETCH BUTTON for ALL providers
        fetch_btn = QPushButton("Fetch Models")
        fetch_btn.setFixedWidth(120)
        fetch_btn.setStyleSheet("background-color: #2d2d2d; border: 1px solid #3e3e42;")
        fetch_btn.clicked.connect(lambda: self.fetch_models_for_provider(p_id))
        key_layout.addWidget(fetch_btn)
        
        key_group.setLayout(key_layout)
        layout.addWidget(key_group)
        
        # --- Models ---
        models_group = QGroupBox("Model Selection")
        models_layout = QVBoxLayout()
        
        # Lists container
        lists_bg = QWidget()
        lists_layout = QHBoxLayout(lists_bg)
        lists_layout.setContentsMargins(0,0,0,0)
        
        # Available
        v1 = QVBoxLayout()
        v1.addWidget(QLabel("Available Models"))
        available_list = QListWidget()
        available_list.setSelectionMode(QListWidget.MultiSelection)
        available_list.setStyleSheet("background: #252526; border: 1px solid #3c3c3c;")
        v1.addWidget(available_list)
        lists_layout.addLayout(v1)
        
        # Buttons
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
        
        # Selected
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
            "fetch_btn": fetch_btn
        }
        
        # Populate Lists
        self.populate_lists(p_id, p_name, p_defaults, available_list, selected_list)

    def populate_lists(self, p_id, p_name, p_defaults, available_list, selected_list):
        available_list.clear() # Keep selected? No, re-populating from scratch based on global enabled set
        selected_list.clear()
        
        # Logic: 
        # 1. Add all enabled models that belong to this provider to Selected List.
        # 2. Add all default models that are NOT in enabled models to Available List.
        
        prefix = f"[{p_name}] "
        
        # Find enabled for this provider
        provider_enabled = []
        for em in self.enabled_models:
            if em.startswith(prefix):
                 provider_enabled.append(em)
        
        for em in provider_enabled:
            selected_list.addItem(em)
            
        # Defaults -> Available
        for code in p_defaults:
            full = f"{prefix}{code}"
            if full not in self.enabled_models:
                available_list.addItem(full)

    def move_items(self, source_list, target_list):
        for item in source_list.selectedItems():
            row = source_list.row(item)
            text = item.text()
            
            # Check limits? 
            # if target_list == selected and target count >= 5? 
            
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
        
        # Call Client
        try:
            # We temporarily save the key to settings manager just in case the client needs it from there
            # (though prefer passing it directly)
            if p_id == "openrouter":
                self.settings_manager.set_openrouter_key(key)
            else:
                self.settings_manager.set_api_key(p_id, key)

            models = AIClient.fetch_models(p_id, key, self.settings_manager.get_local_llm_url() if p_id == "local" else None)
        except Exception as e:
            models = []
            print(f"Fetch error: {e}")
            
        QApplication.restoreOverrideCursor()
        btn.setText("Fetch Models")
        btn.setEnabled(True)
        
        if models:
            # Add to Available List
            avail_list = ui["available"]
            sel_list = ui["selected"]
            
            # Provider Name match
            p_name = [x[1] for x in self.providers if x[0] == p_id][0]
            prefix = f"[{p_name}] "
            
            existing = set()
            for i in range(avail_list.count()): existing.add(avail_list.item(i).text())
            for i in range(sel_list.count()): existing.add(sel_list.item(i).text())
            
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

    def save_settings(self):
        # 1. Save all keys
        for p_id, _, p_key_name, _ in self.providers:
            input_val = self.provider_ui[p_id]["key_input"].text().strip()
            if p_id == "local":
                self.settings_manager.set_local_llm_url(input_val)
            else:
                self.settings_manager.set_api_key(p_key_name, input_val)
                
        # 2. Collect all selected models from ALL tabs (we need to iterate our UI map)
        all_enabled = []
        for p_id in self.provider_ui:
            sel_list = self.provider_ui[p_id]["selected"]
            for i in range(sel_list.count()):
                all_enabled.append(sel_list.item(i).text())
            
        self.settings_manager.set_enabled_models(all_enabled)
        self.accept()
