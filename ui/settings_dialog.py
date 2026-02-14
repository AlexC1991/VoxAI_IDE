from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit, 
                             QPushButton, QHBoxLayout, QFormLayout, QGroupBox, QListWidget, QListWidgetItem)
from PySide6.QtCore import Qt
from core.settings import SettingsManager
from core.ai_client import AIClient

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(400, 500) # Increased height for model list
        self.settings_manager = SettingsManager()
        
        layout = QVBoxLayout(self)

        # Connectors Group
        api_group = QGroupBox("API Providers")
        api_layout = QFormLayout()
        
        self.openrouter_key_input = QLineEdit()
        self.openrouter_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.openrouter_key_input.setText(self.settings_manager.get_openrouter_key())
        api_layout.addRow("OpenRouter API Key:", self.openrouter_key_input)
        
        self.local_url_input = QLineEdit()
        self.local_url_input.setText(self.settings_manager.get_local_llm_url())
        api_layout.addRow("Local LLM URL:", self.local_url_input)
        
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        # Models Group
        model_group = QGroupBox("AI Models")
        model_layout = QVBoxLayout()
        
        self.fetch_btn = QPushButton("Refresh OpenRouter Models")
        self.fetch_btn.clicked.connect(self.fetch_models)
        model_layout.addWidget(self.fetch_btn)
        
        self.model_list = QListWidget()
        self.model_list.setSelectionMode(QListWidget.NoSelection) # rely on checkboxes
        model_layout.addWidget(self.model_list)
        
        # Load existing models
        self.populate_model_list()
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(self.save_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)

    def populate_model_list(self):
        self.model_list.clear()
        current_models = self.settings_manager.get_custom_models()
        self.add_models_to_list(current_models, checked=True)

    def add_models_to_list(self, models, checked=False):
        existing_items = {self.model_list.item(i).text() for i in range(self.model_list.count())}
        
        for model in models:
            if model not in existing_items:
                item = QListWidgetItem(model)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self.model_list.addItem(item)
                existing_items.add(model)
                
    def fetch_models(self):
        self.fetch_btn.setText("Fetching...")
        self.fetch_btn.setEnabled(False)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents() # Force update
        
        new_models = AIClient.fetch_openrouter_models()
        
        if new_models:
            # We want to keep existing checked models checked
            # And add new ones unchecked
            
            # Get current checked
            checked_models = set()
            for i in range(self.model_list.count()):
                item = self.model_list.item(i)
                if item.checkState() == Qt.Checked:
                    checked_models.add(item.text())
            
            self.model_list.clear()
            
            # Re-add all fetched models
            for model in new_models:
                item = QListWidgetItem(model)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                if model in checked_models or model in self.settings_manager.get_custom_models(): 
                     # Should we auto-check previous custom models? Yes.
                     item.setCheckState(Qt.Checked)
                else:
                     item.setCheckState(Qt.Unchecked)
                self.model_list.addItem(item)
                
            # Keep manual/local models
            for model in checked_models:
                if model not in new_models and (model.startswith("local/") or True):
                     item = QListWidgetItem(model)
                     item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                     item.setCheckState(Qt.Checked)
                     self.model_list.addItem(item)

        self.fetch_btn.setText("Refresh OpenRouter Models")
        self.fetch_btn.setEnabled(True)

    def save_settings(self):
        self.settings_manager.set_openrouter_key(self.openrouter_key_input.text().strip())
        self.settings_manager.set_local_llm_url(self.local_url_input.text().strip())
        
        # Save Models
        selected_models = []
        for i in range(self.model_list.count()):
            item = self.model_list.item(i)
            if item.checkState() == Qt.Checked:
                selected_models.append(item.text())
        
        if selected_models:
            self.settings_manager.set_custom_models(selected_models)
            
        self.accept()
