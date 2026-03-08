
import copy
import os
import requests
import json
import logging
import threading
import time
from core.settings import SettingsManager

# Set up logging
log = logging.getLogger(__name__)

class AIClient:
    OPENROUTER_FREE_MODEL_PRIORITY = [
        "qwen/qwen3-coder:free",
        "z-ai/glm-4.5-air:free",
        "google/gemma-3-4b-it:free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "openai/gpt-oss-20b:free",
    ]
    OPENROUTER_MAX_FALLBACK_MODELS = 5
    OPENROUTER_HEALTHY_TTL_SECONDS = 900
    OPENROUTER_PRECHECK_MAX_PROBES = 3
    OPENROUTER_PROBE_TIMEOUT_SECONDS = 12
    OPENROUTER_RATE_LIMIT_COOLDOWN_SECONDS = 180
    OPENROUTER_POLICY_COOLDOWN_SECONDS = 3600
    OPENROUTER_REQUEST_FAILURE_COOLDOWN_SECONDS = 300
    OPENROUTER_BACKGROUND_REFRESH_INTERVAL_SECONDS = 900
    # Universal Provider Configuration
    # Maps provider_id -> {base_url, header_name, format}
    PROVIDER_CONFIG = {
        "openai": {
            "base_url": "https://api.openai.com/v1/chat/completions",
            "header": "Authorization",
            "format": "openai"
        },
        "anthropic": {
            "base_url": "https://api.anthropic.com/v1/messages",
            "header": "x-api-key",
            "format": "anthropic"
        },
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1/chat/completions",
            "header": "Authorization",
            "format": "openai"
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/chat/completions", 
            "header": "Authorization",
            "format": "openai"
        },
        "google": {
            # Using OpenAI-compatible endpoint for Gemini
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "header": "Authorization",
            "format": "openai"
        },
        "mistral": {
            "base_url": "https://api.mistral.ai/v1/chat/completions",
            "header": "Authorization",
            "format": "openai"
        },
        "xai": {
            "base_url": "https://api.x.ai/v1/chat/completions",
            "header": "Authorization",
            "format": "openai"
        },
        "kimi": {
            "base_url": "https://api.moonshot.cn/v1/chat/completions",
            "header": "Authorization",
            "format": "openai"
        },
        "zai": {
            "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "header": "Authorization",
            "format": "openai"
        },
        "local": {
            "base_url": "{local_url}", # Placeholder for dynamic URL
            "header": None,
            "format": "openai"
        },
        "local_file": {
            "base_url": None,
            "header": None,
            "format": "gguf"
        },
        "test": {
            "base_url": None,
            "header": None,
            "format": "scripted"
        }
    }

    # Mapping of Display Name (from UI) back to Provider ID
    DISPLAY_MAP = {
        "OpenAI": "openai",
        "Google Gemini": "google",
        "Anthropic": "anthropic",
        "DeepSeek": "deepseek",
        "Mistral AI": "mistral",
        "xAI (Grok)": "xai",
        "Kimi (Moonshot)": "kimi",
        "Z.ai (Zhipu)": "zai",
        "OpenRouter": "openrouter",
        "Local LLM (Ollama)": "local",
        "Local": "local_file",
        "Test": "test",
    }
    PROVIDER_DISPLAY = {provider: display for display, provider in DISPLAY_MAP.items()}

    _llm_cache = {}  # class-level: {model_name: Llama instance}
    _test_script_lock = threading.Lock()
    _test_script = []
    _test_transcript = []
    DEFAULT_TEST_PROVIDER_SCRIPT = [
        "<list_files path=\"tests\" />",
        "Deterministic test provider completed the IDE agent flow smoke test successfully.",
    ]

    @classmethod
    def configure_test_provider(cls, scripted_responses):
        with cls._test_script_lock:
            cls._test_script = list(scripted_responses or [])
            cls._test_transcript = []

    @classmethod
    def clear_test_provider(cls):
        with cls._test_script_lock:
            cls._test_script = []
            cls._test_transcript = []

    @classmethod
    def get_test_transcript(cls):
        with cls._test_script_lock:
            return copy.deepcopy(cls._test_transcript)

    @classmethod
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
        with AIClient._test_script_lock:
            if AIClient._test_script:
                return
        loaded = self._load_test_provider_script()
        with AIClient._test_script_lock:
            if not AIClient._test_script:
                AIClient._test_script = list(loaded)

    @classmethod
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

    @classmethod
    def format_model_selection(cls, provider_id, model_name):
        provider_id = (provider_id or "openai").lower()
        display = cls.PROVIDER_DISPLAY.get(provider_id)
        if display:
            return f"[{display}] {model_name}"
        return f"[{provider_id}] {model_name}"

    def _get_openrouter_health_snapshot(self):
        getter = getattr(self.settings_manager, "get_openrouter_health_state", None)
        if not callable(getter):
            return {}
        snapshot = getter()
        return snapshot if isinstance(snapshot, dict) else {}

    def _save_openrouter_health_snapshot(self, snapshot):
        setter = getattr(self.settings_manager, "set_openrouter_health_state", None)
        if callable(setter):
            setter(snapshot if isinstance(snapshot, dict) else {})

    @staticmethod
    def _normalize_openrouter_health_entry(entry):
        if not isinstance(entry, dict):
            return {}
        normalized = dict(entry)
        for key in ("last_checked", "last_success_at", "cooldown_until", "score"):
            try:
                normalized[key] = float(normalized.get(key, 0) or 0)
            except Exception:
                normalized[key] = 0.0
        normalized["status"] = str(normalized.get("status", "unknown") or "unknown")
        normalized["last_error"] = str(normalized.get("last_error", "") or "")
        return normalized

    @classmethod
    def _is_recent_openrouter_success(cls, entry, now_ts=None):
        now_ts = now_ts or time.time()
        entry = cls._normalize_openrouter_health_entry(entry)
        last_success_at = entry.get("last_success_at", 0)
        return (
            entry.get("status") == "healthy"
            and last_success_at > 0
            and (now_ts - last_success_at) <= cls.OPENROUTER_HEALTHY_TTL_SECONDS
        )

    @classmethod
    def _should_probe_openrouter_model(cls, entry, now_ts=None):
        now_ts = now_ts or time.time()
        entry = cls._normalize_openrouter_health_entry(entry)
        if cls._is_recent_openrouter_success(entry, now_ts):
            return False
        return entry.get("cooldown_until", 0) <= now_ts

    @classmethod
    def _classify_openrouter_failure(cls, status=None, detail="", message=""):
        text = f"{detail}\n{message}".lower()
        if status == 429 or "rate limit" in text:
            return "rate_limited"
        if status == 404 and ("data policy" in text or "privacy settings" in text):
            return "policy_blocked"
        return "request_failed"

    def _record_openrouter_health(self, model_id, success, status_label=None, message="", source="request"):
        if self.provider != "openrouter":
            return
        snapshot = self._get_openrouter_health_snapshot()
        now_ts = time.time()
        entry = self._normalize_openrouter_health_entry(snapshot.get(model_id, {}))
        score = entry.get("score", 0)

        if success:
            entry.update({
                "status": "healthy",
                "last_checked": now_ts,
                "last_success_at": now_ts,
                "cooldown_until": 0,
                "last_error": "",
                "last_source": source,
                "score": min(score + 4, 20),
            })
        else:
            status_label = status_label or "request_failed"
            cooldown = {
                "rate_limited": self.OPENROUTER_RATE_LIMIT_COOLDOWN_SECONDS,
                "policy_blocked": self.OPENROUTER_POLICY_COOLDOWN_SECONDS,
                "request_failed": self.OPENROUTER_REQUEST_FAILURE_COOLDOWN_SECONDS,
            }.get(status_label, self.OPENROUTER_REQUEST_FAILURE_COOLDOWN_SECONDS)
            penalty = {
                "rate_limited": 4,
                "policy_blocked": 8,
                "request_failed": 3,
            }.get(status_label, 3)
            entry.update({
                "status": status_label,
                "last_checked": now_ts,
                "cooldown_until": now_ts + cooldown,
                "last_error": message[:300],
                "last_source": source,
                "score": max(score - penalty, -20),
            })

        snapshot[model_id] = entry
        self._save_openrouter_health_snapshot(snapshot)

    def _openrouter_preference_score(self, model_id, primary_model, snapshot, now_ts=None):
        now_ts = now_ts or time.time()
        entry = self._normalize_openrouter_health_entry(snapshot.get(model_id, {}))
        priority_map = {
            name.lower(): len(self.OPENROUTER_FREE_MODEL_PRIORITY) - idx
            for idx, name in enumerate(self.OPENROUTER_FREE_MODEL_PRIORITY)
        }

        score = priority_map.get(model_id.lower(), 0)
        if model_id.lower() == (primary_model or "").lower():
            score += 4

        status = entry.get("status", "unknown")
        if self._is_recent_openrouter_success(entry, now_ts):
            score += 100
        elif status == "healthy":
            score += 20
        elif status == "rate_limited":
            score += -80 if entry.get("cooldown_until", 0) > now_ts else -10
        elif status == "policy_blocked":
            score += -120 if entry.get("cooldown_until", 0) > now_ts else -40
        elif status == "request_failed":
            score += -60 if entry.get("cooldown_until", 0) > now_ts else -15
        else:
            score += 10

        score += entry.get("score", 0)
        return score

    def _select_model_for_future_runs(self, model_id):
        if self.provider != "openrouter":
            return
        full_model = self.format_model_selection("openrouter", model_id)
        try:
            self.settings_manager.set_selected_model(full_model)
        except Exception:
            pass
        self.model = model_id

    @classmethod
    def _enabled_openrouter_free_models(cls, settings_manager=None):
        settings_manager = settings_manager or SettingsManager()
        getter = getattr(settings_manager, "get_enabled_models", None)
        if not callable(getter):
            return []

        enabled = getter() or []
        filtered = []
        seen = set()
        for item in enabled:
            provider, model_id = cls.parse_model_selection(item)
            if provider != "openrouter" or not cls._is_openrouter_free_model(model_id):
                continue
            lowered = model_id.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            filtered.append(model_id)
        return filtered

    @classmethod
    def should_background_refresh(cls, settings_manager=None):
        settings_manager = settings_manager or SettingsManager()
        api_key = ""
        getter = getattr(settings_manager, "get_api_key", None)
        if callable(getter):
            api_key = getter("openrouter") or ""
        if not api_key:
            return False
        return bool(cls._enabled_openrouter_free_models(settings_manager))

    @classmethod
    def refresh_openrouter_health(cls, settings_manager=None, max_probes=None):
        settings_manager = settings_manager or SettingsManager()
        summary = {
            "probed_models": [],
            "successful_models": [],
            "failed_models": [],
            "recommended_model": None,
            "recommended_full_model": None,
            "skipped_reason": None,
        }

        if not cls.should_background_refresh(settings_manager):
            summary["skipped_reason"] = "not_configured"
            return summary

        selected_full = (settings_manager.get_selected_model() or "").strip()
        selected_provider, selected_model = cls.parse_model_selection(selected_full)
        enabled_models = cls._enabled_openrouter_free_models(settings_manager)

        primary_model = selected_model if selected_provider == "openrouter" and cls._is_openrouter_free_model(selected_model) else ""
        candidates = []
        if primary_model:
            candidates.append(primary_model)
        candidates.extend(enabled_models)
        candidates.extend(cls.OPENROUTER_FREE_MODEL_PRIORITY)

        temp = cls.__new__(cls)
        temp.settings_manager = settings_manager
        temp.provider = "openrouter"
        temp.model = primary_model or (enabled_models[0] if enabled_models else cls.OPENROUTER_FREE_MODEL_PRIORITY[0])
        temp.api_key = settings_manager.get_api_key("openrouter")

        deduped = []
        seen = set()
        for model_id in candidates:
            lowered = model_id.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(model_id)

        snapshot = temp._get_openrouter_health_snapshot()
        now_ts = time.time()
        ranked = sorted(
            deduped,
            key=lambda model_id: (
                -temp._openrouter_preference_score(model_id, primary_model, snapshot, now_ts),
                model_id.lower(),
            ),
        )

        probe_limit = max(1, int(max_probes or cls.OPENROUTER_PRECHECK_MAX_PROBES))
        for model_id in ranked:
            if len(summary["probed_models"]) >= probe_limit:
                break
            if not cls._should_probe_openrouter_model(snapshot.get(model_id), now_ts):
                continue

            ok, message = temp._probe_openrouter_model(model_id)
            summary["probed_models"].append(model_id)
            if ok:
                summary["successful_models"].append(model_id)
            else:
                summary["failed_models"].append({"model": model_id, "message": message})
            snapshot = temp._get_openrouter_health_snapshot()
            now_ts = time.time()

        refreshed_ranked = sorted(
            deduped,
            key=lambda model_id: (
                -temp._openrouter_preference_score(model_id, primary_model, snapshot, now_ts),
                model_id.lower(),
            ),
        )
        if refreshed_ranked:
            summary["recommended_model"] = refreshed_ranked[0]
            summary["recommended_full_model"] = cls.format_model_selection("openrouter", refreshed_ranked[0])

        if not summary["probed_models"] and summary["recommended_model"]:
            summary["skipped_reason"] = "cache_fresh"

        return summary

    @classmethod
    def get_openrouter_health_indicator(cls, settings_manager=None):
        settings_manager = settings_manager or SettingsManager()
        configured = cls.should_background_refresh(settings_manager)
        if not configured:
            return {
                "configured": False,
                "status": "inactive",
                "recommended_model": None,
                "recommended_full_model": None,
                "message": "OpenRouter health: inactive",
            }

        enabled_models = cls._enabled_openrouter_free_models(settings_manager)
        selected_full = (settings_manager.get_selected_model() or "").strip()
        selected_provider, selected_model = cls.parse_model_selection(selected_full)
        primary_model = selected_model if selected_provider == "openrouter" and cls._is_openrouter_free_model(selected_model) else ""

        temp = cls.__new__(cls)
        temp.settings_manager = settings_manager
        temp.provider = "openrouter"
        temp.model = primary_model or (enabled_models[0] if enabled_models else cls.OPENROUTER_FREE_MODEL_PRIORITY[0])

        candidates = []
        if primary_model:
            candidates.append(primary_model)
        candidates.extend(enabled_models)
        candidates.extend(cls.OPENROUTER_FREE_MODEL_PRIORITY)

        deduped = []
        seen = set()
        for model_id in candidates:
            lowered = model_id.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(model_id)

        snapshot = temp._get_openrouter_health_snapshot()
        now_ts = time.time()
        if not deduped:
            return {
                "configured": True,
                "status": "unknown",
                "recommended_model": None,
                "recommended_full_model": None,
                "message": "OpenRouter health: waiting for models",
            }

        ranked = sorted(
            deduped,
            key=lambda model_id: (
                -temp._openrouter_preference_score(model_id, primary_model, snapshot, now_ts),
                model_id.lower(),
            ),
        )
        recommended_model = ranked[0]
        entry = cls._normalize_openrouter_health_entry(snapshot.get(recommended_model, {}))
        status = entry.get("status", "unknown")

        if cls._is_recent_openrouter_success(entry, now_ts):
            status = "healthy"
            prefix = "OpenRouter ready"
        elif status == "rate_limited":
            prefix = "OpenRouter cooling down"
        elif status == "policy_blocked":
            prefix = "OpenRouter policy block"
        elif status == "request_failed":
            prefix = "OpenRouter retrying"
        else:
            prefix = "OpenRouter warming"

        return {
            "configured": True,
            "status": status,
            "recommended_model": recommended_model,
            "recommended_full_model": cls.format_model_selection("openrouter", recommended_model),
            "message": f"{prefix}: {recommended_model}",
        }

    @classmethod
    def auto_select_openrouter_model(cls, settings_manager=None, run_probe=True):
        settings_manager = settings_manager or SettingsManager()
        selected_full = (settings_manager.get_selected_model() or "").strip()
        provider, model_id = cls.parse_model_selection(selected_full)
        if provider != "openrouter" or not cls._is_openrouter_free_model(model_id):
            return selected_full, None

        api_key = settings_manager.get_api_key("openrouter")
        if not api_key:
            return selected_full, None

        temp = cls.__new__(cls)
        temp.settings_manager = settings_manager
        temp.provider = "openrouter"
        temp.model = model_id
        temp.api_key = api_key

        candidates = temp._openrouter_candidate_models()
        if not candidates:
            return selected_full, None

        snapshot = temp._get_openrouter_health_snapshot()
        now_ts = time.time()
        best_model = candidates[0]
        current_healthy = cls._is_recent_openrouter_success(snapshot.get(model_id), now_ts)

        if current_healthy:
            return selected_full, None

        if best_model != model_id and cls._is_recent_openrouter_success(snapshot.get(best_model), now_ts):
            chosen_full = cls.format_model_selection("openrouter", best_model)
            settings_manager.set_selected_model(chosen_full)
            return chosen_full, f"OpenRouter preflight auto-selected healthier model '{best_model}' based on recent health checks."

        if not run_probe:
            return selected_full, None

        probes = 0
        for candidate in candidates:
            if probes >= cls.OPENROUTER_PRECHECK_MAX_PROBES:
                break
            if not cls._should_probe_openrouter_model(snapshot.get(candidate), now_ts):
                continue
            probes += 1
            ok, _ = temp._probe_openrouter_model(candidate)
            if ok:
                chosen_full = cls.format_model_selection("openrouter", candidate)
                settings_manager.set_selected_model(chosen_full)
                if candidate != model_id:
                    return chosen_full, f"OpenRouter preflight auto-selected healthier model '{candidate}'."
                return chosen_full, None

        return selected_full, None

    @classmethod
    def _get_local_llm(cls, model_name):
        """Returns a cached Llama instance, loading it only on first use or model change."""
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

    def __init__(self):
        self.settings_manager = SettingsManager()
        full_model_name = self.settings_manager.get_selected_model()
        self.provider, self.model = self.parse_model_selection(full_model_name)

        self.api_key = self.settings_manager.get_api_key(self.provider)

    def _get_config(self):
        return self.PROVIDER_CONFIG.get(self.provider, self.PROVIDER_CONFIG["openrouter"])

    def _get_url(self):
        config = self._get_config()
        url = config["base_url"]
        
        if self.provider == "local":
            # Start/End slash handling could be tricky, but let's trust settings or normalize
            local_url = self.settings_manager.get_local_llm_url().rstrip('/')
            # If user provided "http://localhost:11434/v1", we use it.
            # If they provided "http://localhost:11434", we might need to append /v1/chat/completions?
            # Standard Ollama/LocalAI usually follows OpenAI format if /v1 is used.
            # Let's assume the user entered the BASE of the API compatible endpoint.
            # Actually, standard is usually .../v1/chat/completions for the full endpoint.
            # But PROVIDER_CONFIG usually stores the FULL endpoint.
            # If local_url ends with /v1, we append /chat/completions
            if local_url.endswith("/v1"):
                return f"{local_url}/chat/completions"
            if "/chat/completions" in local_url:
                return local_url
            return f"{local_url}/v1/chat/completions"
            
        return url

    def _get_headers(self):
        config = self._get_config()
        header_name = config["header"]
        
        headers = {
            "Content-Type": "application/json"
        }
        
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

    @staticmethod
    def _is_openrouter_free_model(model_id: str) -> bool:
        lowered = (model_id or "").lower()
        return ":free" in lowered or "/free" in lowered or lowered.endswith("-free")

    @classmethod
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

        priority_map = {
            model_id.lower(): index
            for index, model_id in enumerate(cls.OPENROUTER_FREE_MODEL_PRIORITY)
        }

        def sort_key(model_id: str):
            lowered = model_id.lower()
            is_free = cls._is_openrouter_free_model(model_id)
            if lowered in priority_map:
                return (0, priority_map[lowered], lowered)
            if is_free:
                return (1, lowered)
            if lowered == "openrouter/auto":
                return (2, lowered)
            return (3, lowered)

        return sorted(deduped, key=sort_key)

    def _openrouter_candidate_models(self):
        primary = self.model
        if self.provider != "openrouter":
            return [primary]
        if not self._is_openrouter_free_model(primary):
            return [primary]

        ordered = [primary]
        for model_id in self.OPENROUTER_FREE_MODEL_PRIORITY:
            if model_id.lower() != primary.lower():
                ordered.append(model_id)

        deduped = []
        seen = set()
        for model_id in ordered:
            lowered = model_id.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(model_id)

        snapshot = self._get_openrouter_health_snapshot()
        now_ts = time.time()
        ranked = sorted(
            deduped,
            key=lambda model_id: (
                -self._openrouter_preference_score(model_id, primary, snapshot, now_ts),
                model_id.lower(),
            ),
        )
        return ranked[:self.OPENROUTER_MAX_FALLBACK_MODELS]

    def _probe_openrouter_model(self, model_id):
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with OK only."}],
            "max_tokens": 8,
            "temperature": 0,
            "stream": False,
        }
        try:
            response = requests.post(
                self._get_url(),
                headers=self._get_headers(),
                json=payload,
                timeout=self.OPENROUTER_PROBE_TIMEOUT_SECONDS,
            )
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                detail = self._extract_response_error_detail(response)
                if detail:
                    setattr(e, "vox_error_detail", detail)
                raise e

            self._record_openrouter_health(model_id, success=True, source="probe")
            return True, ""
        except Exception as e:
            error_msg = self._format_request_error(e, model_id=model_id)
            status_label = self._classify_openrouter_failure(
                status=self._error_status(e),
                detail=self._error_detail(e),
                message=error_msg,
            )
            self._record_openrouter_health(
                model_id,
                success=False,
                status_label=status_label,
                message=error_msg,
                source="probe",
            )
            return False, error_msg

    @staticmethod
    def _error_status(error):
        response = getattr(error, "response", None)
        return getattr(response, "status_code", None)

    def _error_detail(self, error):
        response = getattr(error, "response", None)
        return getattr(error, "vox_error_detail", "") or self._extract_response_error_detail(response)

    def _is_recoverable_openrouter_error(self, error, emitted_any=False):
        if self.provider != "openrouter" or emitted_any:
            return False

        status = self._error_status(error)
        detail = self._error_detail(error).lower()
        if status in (408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524):
            return True
        if status == 404 and "data policy" in detail:
            return True
        if "provider returned error" in detail:
            return True
        return False

    @staticmethod
    def _compact_error_headline(message: str) -> str:
        first_line = (message or "").splitlines()[0].strip()
        return first_line.rstrip(".")

    def _format_fallback_notice(self, previous_model: str, next_model: str, previous_error: str) -> str:
        reason = self._compact_error_headline(previous_error)
        return (
            f"[OpenRouter fallback: '{previous_model}' was unavailable ({reason}). "
            f"Retrying with '{next_model}'.]\n\n"
        )

    def _format_fallback_exhausted_error(self, attempts):
        if not attempts:
            return "OpenRouter fallback failed."

        lines = [
            f"OpenRouter fallback exhausted {len(attempts)} model attempt(s) for the current request.",
            "Attempts:",
        ]
        for model_id, message in attempts:
            lines.append(f"- {model_id}: {self._compact_error_headline(message)}")
        return "\n".join(lines)

    @staticmethod
    def _trim_error_detail(detail, max_len=500):
        detail = (detail or "").strip()
        if len(detail) <= max_len:
            return detail
        return detail[:max_len] + "..."

    @classmethod
    def _extract_response_error_detail(cls, response):
        if response is None:
            return ""

        try:
            error_body = response.json()
            error = error_body.get("error")
            if isinstance(error, dict):
                detail = error.get("message") or error.get("detail") or json.dumps(error)
            elif error:
                detail = str(error)
            else:
                detail = json.dumps(error_body)
            return cls._trim_error_detail(detail)
        except Exception:
            pass

        try:
            return cls._trim_error_detail(response.text)
        except Exception:
            return ""

    def _format_request_error(self, error, model_id=None):
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        detail = getattr(error, "vox_error_detail", "") or self._extract_response_error_detail(response)
        model_name = model_id or self.model

        if status == 402:
            return (
                "Provider Error: Insufficient Credits (402 Payment Required).\n"
                "Please top up your OpenRouter/provider balance."
            )

        if self.provider == "openrouter":
            if status == 429:
                msg = (
                    f"OpenRouter rate limit reached for model '{model_name}'.\n"
                    "Wait a minute, try another free model, or reduce request frequency."
                )
                if detail:
                    msg += f"\nProvider said: {detail}"
                return msg

            if status == 404 and "data policy" in detail.lower():
                msg = (
                    f"OpenRouter blocked model '{model_name}' because your privacy settings do not allow this free-model route.\n"
                    "Open https://openrouter.ai/settings/privacy and enable the required privacy/data-sharing setting, then retry."
                )
                if detail:
                    msg += f"\nProvider said: {detail}"
                return msg

            if status is not None:
                msg = f"OpenRouter request failed for model '{model_name}' ({status})."
                if detail:
                    msg += f"\nProvider said: {detail}"
                return msg

        error_msg = f"AI Request Failed: {error}"
        if detail:
            error_msg += f"\nServer Response: {detail}"
        return error_msg

    def _build_payload(self, messages, fmt, model_name=None):
        model_name = model_name or self.model
        payload = {}

        if fmt == "openai":
            payload = {
                "model": model_name,
                "messages": messages,
                "stream": True
            }

        elif fmt == "anthropic":
            system_parts = []
            filtered_msgs = []

            for m in messages:
                if m["role"] == "system":
                    system_parts.append(m["content"])
                else:
                    new_m = m.copy()

                    if isinstance(new_m["content"], list):
                        new_content = []
                        for block in new_m["content"]:
                            if block.get("type") == "image_url":
                                img_url = block["image_url"]["url"]
                                if img_url.startswith("data:"):
                                    try:
                                        header, b64data = img_url.split("base64,")
                                        mime = header.replace("data:", "").replace(";", "")
                                        new_content.append({
                                            "type": "image",
                                            "source": {
                                                "type": "base64",
                                                "media_type": mime,
                                                "data": b64data
                                            }
                                        })
                                    except (ValueError, IndexError):
                                        pass
                            else:
                                new_content.append(block)
                        new_m["content"] = new_content

                    filtered_msgs.append(new_m)

            system_msg = "\n\n".join(system_parts)

            payload = {
                "model": model_name,
                "messages": filtered_msgs,
                "stream": True,
                "max_tokens": 4096
            }
            if system_msg:
                payload["system"] = system_msg

        return payload

    def _stream_remote_attempt(self, url, headers, payload, fmt):
        with requests.post(url, headers=headers, json=payload, stream=True) as response:
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                detail = self._extract_response_error_detail(response)
                if detail:
                    setattr(e, "vox_error_detail", detail)
                raise e

            for line in response.iter_lines():
                if not line:
                    continue

                line_text = line.decode('utf-8').strip()

                if fmt == "openai":
                    if line_text.startswith("data: "):
                        data_str = line_text[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except json.JSONDecodeError:
                            pass

                elif fmt == "anthropic":
                    if line_text.startswith("data: "):
                        data_str = line_text[6:]
                        try:
                            data = json.loads(data_str)
                            if data["type"] == "content_block_delta":
                                yield data["delta"]["text"]
                        except (json.JSONDecodeError, KeyError, TypeError):
                            pass

    def _stream_test_provider(self, messages):
        self._ensure_test_provider_script_loaded()
        scripted_chunks = AIClient._next_test_provider_output(messages)
        if scripted_chunks is None:
            yield "\n[Error: Test provider script exhausted before the agent run completed.]\n"
            return
        for chunk in scripted_chunks:
            yield chunk

    def stream_chat(self, messages):
        """
        Yields chunks of text response from the AI provider.
        """
        if self.provider == "test":
            yield from self._stream_test_provider(messages)
            return

        url = self._get_url()
        headers = self._get_headers()
        config = self._get_config()
        fmt = config.get("format", "openai")

        if self.provider != "local_file":
            attempts = []
            candidate_models = self._openrouter_candidate_models()

            for idx, model_id in enumerate(candidate_models):
                payload = self._build_payload(messages, fmt, model_name=model_id)
                emitted_any = False
                pending_notice = None
                if idx > 0 and attempts:
                    previous_model, previous_error = attempts[-1]
                    pending_notice = self._format_fallback_notice(previous_model, model_id, previous_error)

                try:
                    for chunk in self._stream_remote_attempt(url, headers, payload, fmt):
                        if pending_notice:
                            yield pending_notice
                            pending_notice = None
                        emitted_any = True
                        yield chunk
                    if self.provider == "openrouter":
                        self._record_openrouter_health(model_id, success=True, source="request")
                        self._select_model_for_future_runs(model_id)
                    return
                except Exception as e:
                    error_msg = self._format_request_error(e, model_id=model_id)
                    if self.provider == "openrouter":
                        status_label = self._classify_openrouter_failure(
                            status=self._error_status(e),
                            detail=self._error_detail(e),
                            message=error_msg,
                        )
                        self._record_openrouter_health(
                            model_id,
                            success=False,
                            status_label=status_label,
                            message=error_msg,
                            source="request",
                        )
                    if self._is_recoverable_openrouter_error(e, emitted_any=emitted_any) and idx < len(candidate_models) - 1:
                        log.warning("OpenRouter attempt failed for %s; trying fallback. %s", model_id, self._compact_error_headline(error_msg))
                        attempts.append((model_id, error_msg))
                        continue

                    if attempts:
                        attempts.append((model_id, error_msg))
                        error_msg = self._format_fallback_exhausted_error(attempts)

                    log.error(error_msg)
                    yield f"\n[Error: {error_msg}]\n"
                    return

        if self.provider == "local_file":
            # GGUF Inference via llama-cpp-python (singleton-cached model)
            try:
                llm = AIClient._get_local_llm(self.model)

                flat_messages = []
                for m in messages:
                    c = m.get("content", "")
                    if isinstance(c, list):
                        c = "\n".join(
                            block.get("text", "") for block in c if block.get("type") == "text"
                        )
                    flat_messages.append({"role": m["role"], "content": c})

                stream = llm.create_chat_completion(
                    messages=flat_messages,
                    stream=True
                )

                for chunk in stream:
                    if "choices" in chunk and len(chunk["choices"]) > 0:
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]

            except ImportError:
                yield "\n[Error: llama-cpp-python not installed. Please run `pip install llama-cpp-python`]\n"
            except Exception as e:
                log.error(f"Local Inference Failed: {e}")
                yield f"\n[Error: Local Inference Failed: {e}]\n"


    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Generates embeddings for a list of texts using the local embedding engine.
        """
        try:
            from core.local_embeddings import VoxLocalEmbedder
            embedder = VoxLocalEmbedder.get_instance()
            result = embedder.embed(texts)
            return result if result else []
        except Exception as e:
            log.error(f"Embedding failed: {e}")
            return []

    @staticmethod
    def fetch_models(provider_id, api_key, local_url=None):
        """
        Fetches available models from the provider.
        Returns a list of model IDs.
        """
        try:
            # 1. Determine Base URL
            config = AIClient.PROVIDER_CONFIG.get(provider_id)
            if not config:
                if provider_id == "local":
                    config = AIClient.PROVIDER_CONFIG["local"]
                else:
                    return []

            base_url = config["base_url"]
            header_name = config["header"]

            # Local URL override
            if provider_id == "local":
                if local_url:
                    base_url = local_url
                else:
                    base_url = "http://localhost:11434"
                
                # Normalize typical Ollama/LocalAI endpoints
                if base_url.endswith("/v1"):
                    models_url = f"{base_url}/models"
                else:
                    # Try /api/tags (Ollama native) first, or assume /v1/models?
                    # Let's try /v1/models if checking for compatibility
                    # But if user put http://localhost:11434, might want api/tags
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

            # 2. Prepare Headers
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

            return AIClient._sort_model_ids(provider_id, model_ids)

        except Exception as e:
            log.error("Error fetching models for %s: %s", provider_id, e)
            if hasattr(e, "response") and e.response is not None:
                log.error("Response body: %s", e.response.text)
            return []
