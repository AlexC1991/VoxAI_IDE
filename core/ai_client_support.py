import copy
import json
import logging
import os

import requests


log = logging.getLogger(__name__)


def configure_test_provider(cls, scripted_responses):
    with cls._test_script_lock:
        cls._test_script = list(scripted_responses or [])
        cls._test_transcript = []


def clear_test_provider(cls):
    with cls._test_script_lock:
        cls._test_script = []
        cls._test_transcript = []


def get_test_transcript(cls):
    with cls._test_script_lock:
        return copy.deepcopy(cls._test_transcript)


def _next_test_provider_output(cls, messages):
    with cls._test_script_lock:
        cls._test_transcript.append(copy.deepcopy(messages))
        if not cls._test_script:
            return None
        item = cls._test_script.pop(0)

    if callable(item):
        item = item(copy.deepcopy(messages))
    if isinstance(item, dict):
        if "chunks" in item:
            return [str(chunk) for chunk in item.get("chunks") or []]
        return [str(item.get("response", ""))]
    if isinstance(item, (list, tuple)):
        return [str(chunk) for chunk in item]
    return [str(item)]


def _load_test_provider_script(self):
    script_path = ""
    if hasattr(self, 'settings_manager') and self.settings_manager is not None:
        getter = getattr(self.settings_manager, 'get_test_provider_script_abspath', None)
        if callable(getter):
            script_path = getter() or ""

    if script_path and os.path.exists(script_path):
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("steps") or data.get("script") or []
            if isinstance(data, list) and data:
                return data
        except Exception as e:
            log.warning("Failed to load test provider script from %s: %s", script_path, e)

    return list(self.DEFAULT_TEST_PROVIDER_SCRIPT)


def _ensure_test_provider_script_loaded(self):
    with self.__class__._test_script_lock:
        if self.__class__._test_script:
            return
    loaded = self._load_test_provider_script()
    with self.__class__._test_script_lock:
        if not self.__class__._test_script:
            self.__class__._test_script = list(loaded)


def parse_model_selection(cls, full_model_name):
    full_model_name = (full_model_name or "").strip()
    provider = "openai"
    model = full_model_name

    import re
    match = re.match(r"^\[(.*?)\]\s*(.*)$", full_model_name)
    if match:
        display_name = match.group(1)
        model_name = match.group(2)
        provider = cls.DISPLAY_MAP.get(display_name, display_name.lower())
        model = model_name
    elif "/" in full_model_name:
        provider, model = full_model_name.split("/", 1)
    elif full_model_name.startswith("[Local] "):
        provider = "local_file"
        model = full_model_name.replace("[Local] ", "", 1)

    provider = (provider or "openai").lower()
    if provider not in cls.PROVIDER_CONFIG:
        provider = "openrouter"
        model = full_model_name

    return provider, model


def format_model_selection(cls, provider_id, model_name):
    provider_id = (provider_id or "openai").lower()
    display = cls.PROVIDER_DISPLAY.get(provider_id)
    if display:
        return f"[{display}] {model_name}"
    return f"[{provider_id}] {model_name}"


def _is_provider_configured(cls, provider_id, settings_manager) -> bool:
    provider_id = (provider_id or "openai").lower()
    if provider_id in {"local", "local_file", "test"}:
        return True
    getter = getattr(settings_manager, "get_api_key", None)
    if not callable(getter):
        return False
    return bool((getter(provider_id) or "").strip())


def _show_unstable_models(cls, settings_manager) -> bool:
    getter = getattr(settings_manager, "get_show_unstable_models", None)
    if not callable(getter):
        return False
    try:
        return bool(getter())
    except Exception:
        return False


def _get_local_llm(cls, model_name):
    from llama_cpp import Llama

    if model_name in cls._llm_cache:
        log.debug("Reusing cached GGUF model: %s", model_name)
        return cls._llm_cache[model_name]

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_path = os.path.join(base_dir, "models", "llm", model_name)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found at {model_path}")

    log.info("Loading GGUF model (first use): %s", model_path)
    try:
        from core.hardware import get_hardware_config
        _, hw, _ = get_hardware_config()
    except Exception:
        hw = {"n_gpu_layers": -1, "n_threads": 4, "n_batch": 512, "flash_attn": False}

    llm = Llama(
        model_path=model_path,
        n_ctx=4096,
        n_gpu_layers=hw.get("n_gpu_layers", -1),
        n_threads=hw.get("n_threads", 4),
        n_batch=hw.get("n_batch", 512),
        flash_attn=hw.get("flash_attn", False),
        verbose=False,
    )
    cls._llm_cache[model_name] = llm
    log.info("GGUF model loaded and cached: %s", model_name)
    return llm


def __init__(self, selected_full_model=None, settings_manager=None):
    self.settings_manager = settings_manager or self._default_settings_manager()
    full_model_name = (selected_full_model or self.settings_manager.get_selected_model() or "").strip()
    self.provider, self.model = self.parse_model_selection(full_model_name)
    self.api_key = self.settings_manager.get_api_key(self.provider)


def _get_config(self):
    return self.PROVIDER_CONFIG.get(self.provider, self.PROVIDER_CONFIG["openrouter"])


def _get_url(self):
    config = self._get_config()
    url = config["base_url"]
    if self.provider == "local":
        local_url = self.settings_manager.get_local_llm_url().rstrip('/')
        if local_url.endswith("/v1"):
            return f"{local_url}/chat/completions"
        if "/chat/completions" in local_url:
            return local_url
        return f"{local_url}/v1/chat/completions"
    return url


def _get_headers(self):
    config = self._get_config()
    header_name = config["header"]
    headers = {"Content-Type": "application/json"}

    if self.provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/VoxAI"
        headers["X-Title"] = "VoxAI IDE"

    if header_name and self.api_key:
        if header_name == "Authorization":
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers[header_name] = self.api_key

    if self.provider == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    return headers


def _is_openrouter_free_model(model_id: str) -> bool:
    lowered = (model_id or "").lower()
    return ":free" in lowered or "/free" in lowered or lowered.endswith("-free")


def _sort_model_ids(cls, provider_id, model_ids):
    deduped = []
    seen = set()
    for model_id in model_ids:
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        deduped.append(model_id)

    if provider_id != "openrouter":
        return sorted(deduped)

    priority_map = {model_id.lower(): index for index, model_id in enumerate(cls.OPENROUTER_UI_PRIORITY)}

    def sort_key(model_id: str):
        lowered = model_id.lower()
        is_free = cls._is_openrouter_free_model(model_id)
        if lowered in priority_map:
            return (0, priority_map[lowered], lowered)
        if is_free:
            return (1, lowered)
        return (2, lowered)

    return sorted(deduped, key=sort_key)


def fetch_models(cls, provider_id, api_key, local_url=None):
    try:
        config = cls.PROVIDER_CONFIG.get(provider_id)
        if not config:
            if provider_id == "local":
                config = cls.PROVIDER_CONFIG["local"]
            else:
                return []

        base_url = config["base_url"]
        header_name = config["header"]
        if provider_id == "local":
            base_url = local_url or "http://localhost:11434"
            if base_url.endswith("/v1"):
                models_url = f"{base_url}/models"
            else:
                models_url = f"{base_url}/api/tags"
        else:
            if not base_url or base_url.startswith("{"):
                return []
            if provider_id == "google":
                models_url = "https://generativelanguage.googleapis.com/v1beta/models"
            elif "/chat/completions" in base_url:
                models_url = base_url.replace("/chat/completions", "/models")
            elif "/messages" in base_url:
                models_url = "https://api.anthropic.com/v1/models"
            else:
                models_url = f"{base_url}/models"

        headers = {}
        if header_name and api_key:
            if header_name == "Authorization":
                headers["Authorization"] = f"Bearer {api_key}"
            else:
                headers[header_name] = api_key
        if provider_id == "anthropic":
            headers["anthropic-version"] = "2023-06-01"

        log.debug("Fetching models from %s", models_url)
        if provider_id == "local" and "api/tags" in models_url:
            response = requests.get(models_url, timeout=10)
        else:
            response = requests.get(models_url, headers=headers, timeout=10)

        response.raise_for_status()
        data = response.json()
        model_ids = []
        if "data" in data and isinstance(data["data"], list):
            for item in data["data"]:
                if "id" in item:
                    model_ids.append(item["id"])
        elif "models" in data and isinstance(data["models"], list):
            for item in data["models"]:
                if "name" in item:
                    model_ids.append(item["name"])
                elif "id" in item:
                    model_ids.append(item["id"])
        else:
            log.warning("Unknown model list format: %s", list(data.keys()))
        return cls._sort_model_ids(provider_id, model_ids)
    except Exception as e:
        log.error("Error fetching models for %s: %s", provider_id, e)
        if hasattr(e, "response") and e.response is not None:
            log.error("Response body: %s", e.response.text)
        return []