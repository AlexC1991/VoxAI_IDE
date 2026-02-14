from PySide6.QtCore import QSettings

class SettingsManager:
    def __init__(self):
        # Avoid spamming prints if instantiated often, but good for now
        # print("[DEBUG] SettingsManager instantiated")
        self.settings = QSettings("VoxAI", "CodingAgentIDE")
        self.load_secrets()

    def load_secrets(self):
        """Loads secrets from keys/secrets.json if it exists, initializing settings."""
        import os
        import json
        
        # Determine path relative to this file (core/settings.py -> ../keys/secrets.json)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        secrets_path = os.path.join(base_dir, "keys", "secrets.json")
        
        if os.path.exists(secrets_path):
            try:
                with open(secrets_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Load API Keys
                if "api_keys" in data:
                    for key, value in data["api_keys"].items():
                        # Only set if not already manually set (or always overwrite? Let's overwrite to allow file control)
                        self.settings.setValue(f"api_keys/{key}", value)
                        
                # Load URLs
                if "urls" in data:
                    for key, value in data["urls"].items():
                         self.settings.setValue(f"urls/{key}", value)
                         
                print(f"[Settings] Loaded secrets from {secrets_path}")
            except Exception as e:
                print(f"[Settings] Error loading secrets: {e}")

    def get_openrouter_key(self):
        return self.settings.value("api_keys/openrouter", "")

    def set_openrouter_key(self, key):
        self.settings.setValue("api_keys/openrouter", key)

    def get_local_llm_url(self):
        return self.settings.value("urls/local_llm", "http://localhost:11434/v1")

    def set_local_llm_url(self, url):
        self.settings.setValue("urls/local_llm", url)

    def get_selected_model(self):
        return self.settings.value("models/selected", "openai/gpt-4o")

    def set_selected_model(self, model):
        self.settings.setValue("models/selected", model)
    
    def get_custom_models(self):
        # Return a list of custom models if any, generic defaults otherwise
        default_models = [
            "openai/gpt-4o",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-pro-1.5",
            "local/llama3",
            "local/mistral", 
            "deepseek/deepseek-coder"
        ]
        stored = self.settings.value("models/list", default_models)
        return stored if isinstance(stored, list) else default_models

    def set_custom_models(self, models):
        self.settings.setValue("models/list", models)

    def get_entry_point_script(self):
        return self.settings.value("entry_point_script", "")

    def set_entry_point_script(self, path):
        self.settings.setValue("entry_point_script", path)

    def get_last_project_path(self):
        return self.settings.value("project/path", "")

    def set_last_project_path(self, path):
        self.settings.setValue("project/path", path)
