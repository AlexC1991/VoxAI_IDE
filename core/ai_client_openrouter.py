import json
import logging
import time

import requests


log = logging.getLogger(__name__)


def get_model_availability(cls, full_model_name, settings_manager=None):
    settings_manager = settings_manager or cls._default_settings_manager()
    full_model_name = (full_model_name or "").strip()
    provider, model_id = cls.parse_model_selection(full_model_name)
    result = {
        "full_model_name": full_model_name,
        "provider": provider,
        "model_id": model_id,
        "status": "available",
        "reason": "",
        "visible_by_default": True,
        "send_allowed": True,
        "recommended_full_model": None,
    }
    route_reason = cls.QUARANTINED_MODEL_ROUTES.get((provider, model_id))
    if route_reason:
        result.update({"status": "quarantined", "reason": route_reason, "visible_by_default": False, "send_allowed": False})
        return result
    if not cls._is_provider_configured(provider, settings_manager):
        result.update({
            "status": "missing_api_key",
            "reason": f"{cls.PROVIDER_DISPLAY.get(provider, provider)} is not configured.",
            "visible_by_default": False,
            "send_allowed": False,
        })
        return result
    if provider == "openrouter":
        indicator = cls.get_openrouter_health_indicator(settings_manager)
        result["recommended_full_model"] = indicator.get("recommended_full_model")
        if cls._is_openrouter_free_model(model_id):
            temp = cls.__new__(cls)
            temp.settings_manager = settings_manager
            temp.provider = "openrouter"
            temp.model = model_id
            snapshot = temp._get_openrouter_health_snapshot()
            entry = cls._normalize_openrouter_health_entry(snapshot.get(model_id, {}))
            now_ts = time.time()
            status = entry.get("status", "unknown")
            cooldown_until = float(entry.get("cooldown_until", 0) or 0)
            if cls._is_recent_openrouter_success(entry, now_ts):
                result["status"] = "healthy"
            elif status in {"rate_limited", "policy_blocked", "request_failed"} and cooldown_until > now_ts:
                result.update({
                    "status": status,
                    "reason": entry.get("last_error") or indicator.get("message") or "OpenRouter route is cooling down.",
                    "visible_by_default": False,
                    "send_allowed": False,
                })
            else:
                result["status"] = status or "unknown"
    return result


def get_model_picker_entry(cls, full_model_name, settings_manager=None):
    settings_manager = settings_manager or cls._default_settings_manager()
    availability = cls.get_model_availability(full_model_name, settings_manager)
    short = (availability.get("model_id") or full_model_name or "").rsplit("/", 1)[-1]
    label = short
    tooltip_lines = [full_model_name] if full_model_name else []
    status = availability["status"]
    reason = availability.get("reason") or ""
    if full_model_name == cls.DEFAULT_BENCHMARK_MODEL:
        label += " ★"
    if status == "quarantined":
        label += " ⛔"
        tooltip_lines.append(f"Quarantined: {reason}")
    elif status == "missing_api_key":
        label += " 🔑"
        tooltip_lines.append(reason)
    elif status in {"rate_limited", "policy_blocked", "request_failed"}:
        label += " ⏳"
        tooltip_lines.append(f"Cooling down: {reason}")
    elif status == "healthy" and availability.get("provider") == "openrouter":
        tooltip_lines.append("Recently healthy via OpenRouter preflight checks.")
    availability["label"] = label
    availability["tooltip"] = "\n".join(line for line in tooltip_lines if line)
    availability["show_in_picker"] = availability["visible_by_default"] or cls._show_unstable_models(settings_manager)
    availability["show_in_settings"] = availability["visible_by_default"] or cls._show_unstable_models(settings_manager)
    return availability


def recommended_enabled_model(cls, settings_manager=None, exclude_full_model=None):
    settings_manager = settings_manager or cls._default_settings_manager()
    enabled_models = list(getattr(settings_manager, "get_enabled_models", lambda: [])() or [])
    indicator = cls.get_openrouter_health_indicator(settings_manager)
    candidates = []
    recommended = indicator.get("recommended_full_model")
    if recommended:
        candidates.append(recommended)
    candidates.extend(enabled_models)
    seen = set()
    for full_model in candidates:
        full_model = (full_model or "").strip()
        if not full_model or full_model == exclude_full_model or full_model in seen:
            continue
        seen.add(full_model)
        availability = cls.get_model_availability(full_model, settings_manager)
        if availability.get("send_allowed"):
            return full_model, availability
    return None, None


def prepare_model_for_request(cls, selected_full_model, settings_manager=None, run_probe=True):
    settings_manager = settings_manager or cls._default_settings_manager()
    selected_full_model = (selected_full_model or "").strip()
    availability = cls.get_model_availability(selected_full_model, settings_manager)
    if availability["provider"] == "openrouter" and availability.get("send_allowed"):
        chosen_full, preflight_note = cls.auto_select_openrouter_model(settings_manager, run_probe=run_probe)
        return {"effective_model": (chosen_full or selected_full_model).strip(), "blocked_reason": None, "note": preflight_note}
    if availability.get("send_allowed"):
        return {"effective_model": selected_full_model, "blocked_reason": None, "note": None}
    fallback_full = availability.get("recommended_full_model")
    fallback_availability = None
    if fallback_full and fallback_full != selected_full_model:
        fallback_availability = cls.get_model_availability(fallback_full, settings_manager)
    if not fallback_full or not fallback_availability or not fallback_availability.get("send_allowed"):
        fallback_full, fallback_availability = cls.recommended_enabled_model(settings_manager, exclude_full_model=selected_full_model)
    if fallback_full and fallback_availability and fallback_availability.get("send_allowed"):
        settings_manager.set_selected_model(fallback_full)
        fallback_short = (fallback_availability.get("model_id") or fallback_full).rsplit("/", 1)[-1]
        note = f"{availability.get('reason') or 'Selected model is unavailable.'} Switched to '{fallback_short}' before sending."
        return {"effective_model": fallback_full, "blocked_reason": None, "note": note}
    return {"effective_model": selected_full_model, "blocked_reason": availability.get("reason") or "Selected model is unavailable.", "note": None}


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


def _is_recent_openrouter_success(cls, entry, now_ts=None):
    now_ts = now_ts or time.time()
    entry = cls._normalize_openrouter_health_entry(entry)
    last_success_at = entry.get("last_success_at", 0)
    return entry.get("status") == "healthy" and last_success_at > 0 and (now_ts - last_success_at) <= cls.OPENROUTER_HEALTHY_TTL_SECONDS


def _should_probe_openrouter_model(cls, entry, now_ts=None):
    now_ts = now_ts or time.time()
    entry = cls._normalize_openrouter_health_entry(entry)
    if cls._is_recent_openrouter_success(entry, now_ts):
        return False
    return entry.get("cooldown_until", 0) <= now_ts


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
        entry.update({"status": "healthy", "last_checked": now_ts, "last_success_at": now_ts, "cooldown_until": 0, "last_error": "", "last_source": source, "score": min(score + 4, 20)})
    else:
        status_label = status_label or "request_failed"
        cooldown = {"rate_limited": self.OPENROUTER_RATE_LIMIT_COOLDOWN_SECONDS, "policy_blocked": self.OPENROUTER_POLICY_COOLDOWN_SECONDS, "request_failed": self.OPENROUTER_REQUEST_FAILURE_COOLDOWN_SECONDS}.get(status_label, self.OPENROUTER_REQUEST_FAILURE_COOLDOWN_SECONDS)
        penalty = {"rate_limited": 4, "policy_blocked": 8, "request_failed": 3}.get(status_label, 3)
        entry.update({"status": status_label, "last_checked": now_ts, "cooldown_until": now_ts + cooldown, "last_error": message[:300], "last_source": source, "score": max(score - penalty, -20)})
    snapshot[model_id] = entry
    self._save_openrouter_health_snapshot(snapshot)


def _openrouter_preference_score(self, model_id, primary_model, snapshot, now_ts=None):
    now_ts = now_ts or time.time()
    entry = self._normalize_openrouter_health_entry(snapshot.get(model_id, {}))
    priority_map = {name.lower(): len(self.OPENROUTER_FREE_MODEL_PRIORITY) - idx for idx, name in enumerate(self.OPENROUTER_FREE_MODEL_PRIORITY)}
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


def _enabled_openrouter_free_models(cls, settings_manager=None):
    settings_manager = settings_manager or cls._default_settings_manager()
    getter = getattr(settings_manager, "get_enabled_models", None)
    if not callable(getter):
        return []
    filtered = []
    seen = set()
    for item in getter() or []:
        provider, model_id = cls.parse_model_selection(item)
        if provider != "openrouter" or not cls._is_openrouter_free_model(model_id):
            continue
        lowered = model_id.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        filtered.append(model_id)
    return filtered


def should_background_refresh(cls, settings_manager=None):
    settings_manager = settings_manager or cls._default_settings_manager()
    api_key = ""
    getter = getattr(settings_manager, "get_api_key", None)
    if callable(getter):
        api_key = getter("openrouter") or ""
    if not api_key:
        return False
    return bool(cls._enabled_openrouter_free_models(settings_manager))


def refresh_openrouter_health(cls, settings_manager=None, max_probes=None):
    settings_manager = settings_manager or cls._default_settings_manager()
    summary = {"probed_models": [], "successful_models": [], "failed_models": [], "recommended_model": None, "recommended_full_model": None, "skipped_reason": None}
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
    ranked = sorted(deduped, key=lambda model_id: (-temp._openrouter_preference_score(model_id, primary_model, snapshot, now_ts), model_id.lower()))
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
    refreshed_ranked = sorted(deduped, key=lambda model_id: (-temp._openrouter_preference_score(model_id, primary_model, snapshot, now_ts), model_id.lower()))
    if refreshed_ranked:
        summary["recommended_model"] = refreshed_ranked[0]
        summary["recommended_full_model"] = cls.format_model_selection("openrouter", refreshed_ranked[0])
    if not summary["probed_models"] and summary["recommended_model"]:
        summary["skipped_reason"] = "cache_fresh"
    return summary


def get_openrouter_health_indicator(cls, settings_manager=None):
    settings_manager = settings_manager or cls._default_settings_manager()
    if not cls.should_background_refresh(settings_manager):
        return {"configured": False, "status": "inactive", "recommended_model": None, "recommended_full_model": None, "message": "OpenRouter health: inactive"}
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
        return {"configured": True, "status": "unknown", "recommended_model": None, "recommended_full_model": None, "message": "OpenRouter health: waiting for models"}
    ranked = sorted(deduped, key=lambda model_id: (-temp._openrouter_preference_score(model_id, primary_model, snapshot, now_ts), model_id.lower()))
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


def auto_select_openrouter_model(cls, settings_manager=None, run_probe=True):
    settings_manager = settings_manager or cls._default_settings_manager()
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


def _openrouter_candidate_models(self):
    primary = self.model
    if self.provider != "openrouter" or not self._is_openrouter_free_model(primary):
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
    ranked = sorted(deduped, key=lambda model_id: (-self._openrouter_preference_score(model_id, primary, snapshot, now_ts), model_id.lower()))
    return ranked[:self.OPENROUTER_MAX_FALLBACK_MODELS]


def _probe_openrouter_model(self, model_id):
    payload = {"model": model_id, "messages": [{"role": "user", "content": "Reply with OK only."}], "max_tokens": 8, "temperature": 0, "stream": False}
    try:
        response = requests.post(self._get_url(), headers=self._get_headers(), json=payload, timeout=self.OPENROUTER_PROBE_TIMEOUT_SECONDS)
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
        status_label = self._classify_openrouter_failure(status=self._error_status(e), detail=self._error_detail(e), message=error_msg)
        self._record_openrouter_health(model_id, success=False, status_label=status_label, message=error_msg, source="probe")
        return False, error_msg


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


def _transient_retry_delays(cls, provider_id):
    return tuple(cls.DIRECT_PROVIDER_RETRY_DELAYS_SECONDS.get((provider_id or "").lower(), ()))


def _is_recoverable_direct_provider_error(self, error, emitted_any=False):
    if self.provider in {"openrouter", "local_file", "test"} or emitted_any:
        return False
    if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True
    status = self._error_status(error)
    detail = self._error_detail(error).lower()
    if status in self.REMOTE_TRANSIENT_RETRYABLE_STATUSES:
        return True
    return any(token in detail for token in ("service unavailable", "temporarily unavailable", "high demand", "try again later", "overloaded", "upstream error"))


def _compact_error_headline(message: str) -> str:
    first_line = (message or "").splitlines()[0].strip()
    return first_line.rstrip(".")


def _format_fallback_notice(self, previous_model: str, next_model: str, previous_error: str) -> str:
    reason = self._compact_error_headline(previous_error)
    return f"[OpenRouter fallback: '{previous_model}' was unavailable ({reason}). Retrying with '{next_model}'.]\n\n"


def _format_fallback_exhausted_error(self, attempts):
    if not attempts:
        return "OpenRouter fallback failed."
    lines = [f"OpenRouter fallback exhausted {len(attempts)} model attempt(s) for the current request.", "Attempts:"]
    for model_id, message in attempts:
        lines.append(f"- {model_id}: {self._compact_error_headline(message)}")
    return "\n".join(lines)


def _trim_error_detail(detail, max_len=500):
    detail = (detail or "").strip()
    if len(detail) <= max_len:
        return detail
    return detail[:max_len] + "..."


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
        return "Provider Error: Insufficient Credits (402 Payment Required).\nPlease top up your OpenRouter/provider balance."
    if self.provider == "openrouter":
        if status == 429:
            msg = f"OpenRouter rate limit reached for model '{model_name}'.\nWait a minute, try another free model, or reduce request frequency."
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
    if self.provider == "google" and status in self.REMOTE_TRANSIENT_RETRYABLE_STATUSES:
        msg = (
            f"Google Gemini request temporarily unavailable for model '{model_name}' ({status}).\n"
            "The provider appears busy or rate-limited; VoxAI will retry transient failures automatically, but this request still failed."
        )
        if detail:
            msg += f"\nProvider said: {detail}"
        return msg
    error_msg = f"AI Request Failed: {error}"
    if detail:
        error_msg += f"\nServer Response: {detail}"
    return error_msg