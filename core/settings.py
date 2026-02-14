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

    def get_api_key(self, provider):
        """Returns the API key for a specific provider."""
        # Normalize provider name if needed
        key = f"api_keys/{provider.lower()}"
        return self.settings.value(key, "")

    def set_api_key(self, provider, api_key):
        """Sets the API key for a specific provider."""
        key = f"api_keys/{provider.lower()}"
        self.settings.setValue(key, api_key)

    def get_openrouter_key(self):
        return self.get_api_key("openrouter")

    def set_openrouter_key(self, key):
        self.set_api_key("openrouter", key)

    def get_local_llm_url(self):
        return self.settings.value("urls/local_llm", "http://localhost:11434/v1")

    def set_local_llm_url(self, url):
        self.settings.setValue("urls/local_llm", url)

    def get_selected_model(self):
        return self.settings.value("models/selected", "openai/gpt-4o")

    def set_selected_model(self, model):
        self.settings.setValue("models/selected", model)
    
    def get_enabled_models(self):
        """Returns the list of models enabled by the user (Right side list)."""
        # User requested: "list blank not populate with random LLMs"
        default_models = [] 
        stored = self.settings.value("models/enabled_list", default_models)
        return stored if isinstance(stored, list) else default_models

    def set_enabled_models(self, models):
        """Sets the list of enabled models."""
        self.settings.setValue("models/enabled_list", models)

    # Legacy support if needed, or remove
    def get_custom_models(self):
        return self.get_enabled_models()

    def set_custom_models(self, models):
        self.set_enabled_models(models)

    def get_entry_point_script(self):
        return self.settings.value("entry_point_script", "")

    def set_entry_point_script(self, path):
        self.settings.setValue("entry_point_script", path)

    def get_last_project_path(self):
        return self.settings.value("project/path", "")

    def set_last_project_path(self, path):
        self.settings.setValue("project/path", path)

