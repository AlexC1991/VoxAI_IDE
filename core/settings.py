
from PySide6.QtCore import QSettings

class SettingsManager:
    _instance = None
    _settings = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._settings = QSettings("VoxAI", "CodingAgentIDE")
        return cls._instance

    def __init__(self):
        # Already initialized via __new__
        pass

    @property
    def settings(self):
        return self._settings

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
                        self.settings.setValue(f"api_keys/{key}", value)

                # Load URLs
                if "urls" in data:
                    for key, value in data["urls"].items():
                        self.settings.setValue(f"urls/{key}", value)

                import logging
                logging.getLogger(__name__).info("Loaded secrets from %s", secrets_path)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("Error loading secrets: %s", e)

    def get_api_key(self, provider):
        """Returns the API key for a specific provider."""
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

    # -----------------------------
    # RAG / Vector engine settings
    # -----------------------------


    def get_rag_enabled(self) -> bool:
        val = self.settings.value("rag/enabled", True)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("1", "true", "yes", "on")

    def set_rag_enabled(self, enabled: bool):
        self.settings.setValue("rag/enabled", bool(enabled))

    def get_rag_top_k(self) -> int:
        try:
            return int(self.settings.value("rag/top_k", 5))
        except Exception:
            return 5

    def set_rag_top_k(self, k: int):
        try:
            k = int(k)
        except Exception:
            k = 5
        self.settings.setValue("rag/top_k", max(1, min(50, k)))

    def get_rag_min_score(self) -> float:
        try:
            return float(self.settings.value("rag/min_score", 0.0))
        except Exception:
            return 0.0

    def set_rag_min_score(self, s: float):
        try:
            s = float(s)
        except Exception:
            s = 0.0
        self.settings.setValue("rag/min_score", max(0.0, s))

    def get_selected_model(self):
        return self.settings.value("models/selected", "openai/gpt-4o")

    def set_selected_model(self, model):
        self.settings.setValue("models/selected", model)

    def get_enabled_models(self):
        """Returns the list of models enabled by the user (Right side list), plus local GGUF models."""
        default_models = []
        stored = self.settings.value("models/enabled_list", default_models)
        if not isinstance(stored, list):
            stored = default_models
            
        # Append local models
        local_models = self.get_local_models()
        # filter out any duplicates if they were somehow saved in stored list
        # We prefix local models with [Local] for UI clarity
        final_list = list(stored)
        for lm in local_models:
            display_name = f"[Local] {lm}"
            if display_name not in final_list:
                final_list.append(display_name)
                
        return final_list

    def set_enabled_models(self, models):
        """Sets the list of enabled models."""
        self.settings.setValue("models/enabled_list", models)

    def get_embedding_model(self) -> str:
        """Returns the model used for generating embeddings."""
        return self.settings.value("models/embedding", "[OpenAI] text-embedding-3-small")

    def set_embedding_model(self, model: str):
        """Sets the model used for generating embeddings."""
        self.settings.setValue("models/embedding", model)

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

    def get_max_history_messages(self) -> int:
        try:
            return int(self.settings.value("context/max_history_messages", 10))
        except (ValueError, TypeError):
            return 10

    def get_max_file_list(self) -> int:
        try:
            return int(self.settings.value("context/max_file_list", 50))
        except (ValueError, TypeError):
            return 50

    def get_rag_max_context(self) -> int:
        try:
            return int(self.settings.value("rag/max_context_chars", 4000))
        except (ValueError, TypeError):
            return 4000

    def get_rag_max_chunk(self) -> int:
        try:
            return int(self.settings.value("rag/max_chunk_chars", 1000))
        except (ValueError, TypeError):
            return 1000

    # -----------------------------
    # Chat Appearance Settings
    # -----------------------------
    def get_chat_user_color(self) -> str:
        return self.settings.value("appearance/chat_user_color", "#ff9900") 

    def set_chat_user_color(self, color: str):
        self.settings.setValue("appearance/chat_user_color", color)

    def get_chat_ai_color(self) -> str:
        return self.settings.value("appearance/chat_ai_color", "#00f3ff")

    def set_chat_ai_color(self, color: str):
        self.settings.setValue("appearance/chat_ai_color", color)

    # -----------------------------
    # Agent Behavior Settings
    # -----------------------------
    def get_max_history_tokens(self) -> int:
        try:
            return int(self.settings.value("context/max_history_tokens", 24000))
        except Exception:
            return 24000

    def set_max_history_tokens(self, val: int):
        self.settings.setValue("context/max_history_tokens", max(4000, min(128000, int(val))))

    def get_auto_approve_writes(self) -> bool:
        val = self.settings.value("agent/auto_approve_writes", False)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("1", "true", "yes", "on")

    def set_auto_approve_writes(self, enabled: bool):
        self.settings.setValue("agent/auto_approve_writes", bool(enabled))

    def get_auto_save_conversation(self) -> bool:
        val = self.settings.value("agent/auto_save_conversation", True)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("1", "true", "yes", "on")

    def set_auto_save_conversation(self, enabled: bool):
        self.settings.setValue("agent/auto_save_conversation", bool(enabled))

    def get_web_search_enabled(self) -> bool:
        val = self.settings.value("agent/web_search_enabled", True)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("1", "true", "yes", "on")

    def set_web_search_enabled(self, enabled: bool):
        self.settings.setValue("agent/web_search_enabled", bool(enabled))

    def get_local_models(self):
        """Scans the models/llm directory for .gguf files."""
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        models_dir = os.path.join(base_dir, "models", "llm")
        
        if not os.path.exists(models_dir):
            return []
            
        files = [f for f in os.listdir(models_dir) if f.endswith(".gguf")]
        return files
