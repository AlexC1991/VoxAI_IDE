import copy
import json
import logging
import os
import threading
import time

import requests

from core.ai_client_openrouter import (
    _classify_openrouter_failure,
    _compact_error_headline,
    _enabled_openrouter_free_models,
    _error_detail,
    _error_status,
    _extract_response_error_detail,
    _format_fallback_exhausted_error,
    _format_fallback_notice,
    _format_request_error,
    _get_openrouter_health_snapshot,
    _is_recent_openrouter_success,
    _is_recoverable_direct_provider_error,
    _is_recoverable_openrouter_error,
    _normalize_openrouter_health_entry,
    _openrouter_candidate_models,
    _openrouter_preference_score,
    _probe_openrouter_model,
    _record_openrouter_health,
    _save_openrouter_health_snapshot,
    _select_model_for_future_runs,
    _should_probe_openrouter_model,
    _transient_retry_delays,
    _trim_error_detail,
    auto_select_openrouter_model,
    get_model_availability,
    get_model_picker_entry,
    get_openrouter_health_indicator,
    prepare_model_for_request,
    recommended_enabled_model,
    refresh_openrouter_health,
    should_background_refresh,
)
from core.ai_client_runtime import _build_payload, _stream_remote_attempt, _stream_test_provider, embed_texts, stream_chat
from core.ai_client_support import (
    __init__,
    _ensure_test_provider_script_loaded,
    _get_config,
    _get_headers,
    _get_local_llm,
    _get_url,
    _is_openrouter_free_model,
    _is_provider_configured,
    _load_test_provider_script,
    _next_test_provider_output,
    _show_unstable_models,
    _sort_model_ids,
    clear_test_provider,
    configure_test_provider,
    fetch_models,
    format_model_selection,
    get_test_transcript,
    parse_model_selection,
)
from core.settings import SettingsManager


log = logging.getLogger(__name__)


class AIClient:
    OPENROUTER_FREE_MODEL_PRIORITY = [
        "qwen/qwen3-coder:free",
        "z-ai/glm-4.5-air:free",
        "google/gemma-3-4b-it:free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "openai/gpt-oss-20b:free",
    ]
    DEFAULT_BENCHMARK_MODEL = SettingsManager.DEFAULT_BENCHMARK_MODEL
    OPENROUTER_UI_PRIORITY = [DEFAULT_BENCHMARK_MODEL.split("] ", 1)[1], *OPENROUTER_FREE_MODEL_PRIORITY, "openrouter/auto"]
    OPENROUTER_MAX_FALLBACK_MODELS = 5
    OPENROUTER_HEALTHY_TTL_SECONDS = 900
    OPENROUTER_PRECHECK_MAX_PROBES = 3
    OPENROUTER_PROBE_TIMEOUT_SECONDS = 12
    OPENROUTER_RATE_LIMIT_COOLDOWN_SECONDS = 180
    OPENROUTER_POLICY_COOLDOWN_SECONDS = 3600
    OPENROUTER_REQUEST_FAILURE_COOLDOWN_SECONDS = 300
    OPENROUTER_BACKGROUND_REFRESH_INTERVAL_SECONDS = 900
    REMOTE_TRANSIENT_RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}
    DIRECT_PROVIDER_RETRY_DELAYS_SECONDS = {"google": (1.0, 2.0)}
    PROVIDER_CONFIG = {
        "openai": {"base_url": "https://api.openai.com/v1/chat/completions", "header": "Authorization", "format": "openai"},
        "anthropic": {"base_url": "https://api.anthropic.com/v1/messages", "header": "x-api-key", "format": "anthropic"},
        "openrouter": {"base_url": "https://openrouter.ai/api/v1/chat/completions", "header": "Authorization", "format": "openai"},
        "deepseek": {"base_url": "https://api.deepseek.com/chat/completions", "header": "Authorization", "format": "openai"},
        "google": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "header": "Authorization", "format": "openai"},
        "mistral": {"base_url": "https://api.mistral.ai/v1/chat/completions", "header": "Authorization", "format": "openai"},
        "xai": {"base_url": "https://api.x.ai/v1/chat/completions", "header": "Authorization", "format": "openai"},
        "kimi": {"base_url": "https://api.moonshot.cn/v1/chat/completions", "header": "Authorization", "format": "openai"},
        "zai": {"base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "header": "Authorization", "format": "openai"},
        "local": {"base_url": "{local_url}", "header": None, "format": "openai"},
        "local_file": {"base_url": None, "header": None, "format": "gguf"},
        "test": {"base_url": None, "header": None, "format": "scripted"},
    }
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
    _llm_cache = {}
    _test_script_lock = threading.Lock()
    _test_script = []
    _test_transcript = []
    DEFAULT_TEST_PROVIDER_SCRIPT = [
        "<list_files path=\"tests\" />",
        "Deterministic test provider completed the IDE agent flow smoke test successfully.",
    ]
    QUARANTINED_MODEL_ROUTES = {
        ("google", "gemini-3-pro-preview"): "Direct Gemini route repeatedly stalled during benchmarked IDE runs.",
        ("google", "gemini-pro-latest"): "Direct Gemini route repeatedly stalled during benchmarked IDE runs.",
        ("openrouter", "anthropic/claude-opus-4.6"): "OpenRouter route repeatedly returned provider 400 errors during benchmark runs.",
        ("openrouter", "anthropic/claude-sonnet-4.6"): "OpenRouter route repeatedly returned provider 400 errors during benchmark runs.",
    }

    @staticmethod
    def _default_settings_manager():
        return SettingsManager()

    configure_test_provider = classmethod(configure_test_provider)
    clear_test_provider = classmethod(clear_test_provider)
    get_test_transcript = classmethod(get_test_transcript)
    _next_test_provider_output = classmethod(_next_test_provider_output)
    _load_test_provider_script = _load_test_provider_script
    _ensure_test_provider_script_loaded = _ensure_test_provider_script_loaded
    parse_model_selection = classmethod(parse_model_selection)
    format_model_selection = classmethod(format_model_selection)
    _is_provider_configured = classmethod(_is_provider_configured)
    _show_unstable_models = classmethod(_show_unstable_models)
    _get_local_llm = classmethod(_get_local_llm)
    __init__ = __init__
    _get_config = _get_config
    _get_url = _get_url
    _get_headers = _get_headers
    _is_openrouter_free_model = staticmethod(_is_openrouter_free_model)
    _sort_model_ids = classmethod(_sort_model_ids)
    fetch_models = classmethod(fetch_models)
    get_model_availability = classmethod(get_model_availability)
    get_model_picker_entry = classmethod(get_model_picker_entry)
    recommended_enabled_model = classmethod(recommended_enabled_model)
    prepare_model_for_request = classmethod(prepare_model_for_request)
    _get_openrouter_health_snapshot = _get_openrouter_health_snapshot
    _save_openrouter_health_snapshot = _save_openrouter_health_snapshot
    _normalize_openrouter_health_entry = staticmethod(_normalize_openrouter_health_entry)
    _is_recent_openrouter_success = classmethod(_is_recent_openrouter_success)
    _should_probe_openrouter_model = classmethod(_should_probe_openrouter_model)
    _classify_openrouter_failure = classmethod(_classify_openrouter_failure)
    _record_openrouter_health = _record_openrouter_health
    _openrouter_preference_score = _openrouter_preference_score
    _select_model_for_future_runs = _select_model_for_future_runs
    _enabled_openrouter_free_models = classmethod(_enabled_openrouter_free_models)
    should_background_refresh = classmethod(should_background_refresh)
    refresh_openrouter_health = classmethod(refresh_openrouter_health)
    get_openrouter_health_indicator = classmethod(get_openrouter_health_indicator)
    auto_select_openrouter_model = classmethod(auto_select_openrouter_model)
    _openrouter_candidate_models = _openrouter_candidate_models
    _probe_openrouter_model = _probe_openrouter_model
    _error_status = staticmethod(_error_status)
    _error_detail = _error_detail
    _is_recoverable_openrouter_error = _is_recoverable_openrouter_error
    _transient_retry_delays = classmethod(_transient_retry_delays)
    _is_recoverable_direct_provider_error = _is_recoverable_direct_provider_error
    _compact_error_headline = staticmethod(_compact_error_headline)
    _format_fallback_notice = _format_fallback_notice
    _format_fallback_exhausted_error = _format_fallback_exhausted_error
    _trim_error_detail = staticmethod(_trim_error_detail)
    _extract_response_error_detail = classmethod(_extract_response_error_detail)
    _format_request_error = _format_request_error
    _build_payload = _build_payload
    _stream_remote_attempt = _stream_remote_attempt
    _stream_test_provider = _stream_test_provider
    stream_chat = stream_chat
    embed_texts = embed_texts