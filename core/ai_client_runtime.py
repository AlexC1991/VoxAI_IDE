import json
import logging
import time

import requests


log = logging.getLogger(__name__)


def _build_payload(self, messages, fmt, model_name=None):
    model_name = model_name or self.model
    if fmt == "openai":
        return {"model": model_name, "messages": messages, "stream": True}

    if fmt == "anthropic":
        system_parts = []
        filtered_msgs = []
        for message in messages:
            if message["role"] == "system":
                system_parts.append(message["content"])
                continue

            new_message = message.copy()
            if isinstance(new_message["content"], list):
                new_content = []
                for block in new_message["content"]:
                    if block.get("type") == "image_url":
                        img_url = block["image_url"]["url"]
                        if img_url.startswith("data:"):
                            try:
                                header, b64data = img_url.split("base64,")
                                mime = header.replace("data:", "").replace(";", "")
                                new_content.append({
                                    "type": "image",
                                    "source": {"type": "base64", "media_type": mime, "data": b64data},
                                })
                            except (ValueError, IndexError):
                                pass
                    else:
                        new_content.append(block)
                new_message["content"] = new_content
            filtered_msgs.append(new_message)

        payload = {"model": model_name, "messages": filtered_msgs, "stream": True, "max_tokens": 4096}
        system_msg = "\n\n".join(system_parts)
        if system_msg:
            payload["system"] = system_msg
        return payload

    return {}


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
            if fmt == "openai" and line_text.startswith("data: "):
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
            elif fmt == "anthropic" and line_text.startswith("data: "):
                data_str = line_text[6:]
                try:
                    data = json.loads(data_str)
                    if data["type"] == "content_block_delta":
                        yield data["delta"]["text"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass


def _stream_test_provider(self, messages):
    self._ensure_test_provider_script_loaded()
    scripted_chunks = self.__class__._next_test_provider_output(messages)
    if scripted_chunks is None:
        yield "\n[Error: Test provider script exhausted before the agent run completed.]\n"
        return
    for chunk in scripted_chunks:
        yield chunk


def stream_chat(self, messages):
    if self.provider == "test":
        yield from self._stream_test_provider(messages)
        return

    url = self._get_url()
    headers = self._get_headers()
    fmt = self._get_config().get("format", "openai")
    if self.provider != "local_file":
        attempts = []
        candidate_models = self._openrouter_candidate_models()
        for idx, model_id in enumerate(candidate_models):
            payload = self._build_payload(messages, fmt, model_name=model_id)
            pending_notice = None
            if idx > 0 and attempts:
                previous_model, previous_error = attempts[-1]
                pending_notice = self._format_fallback_notice(previous_model, model_id, previous_error)
            retry_delays = self._transient_retry_delays(self.provider)
            retry_index = 0
            while True:
                emitted_any = False
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
                        status_label = self._classify_openrouter_failure(status=self._error_status(e), detail=self._error_detail(e), message=error_msg)
                        self._record_openrouter_health(model_id, success=False, status_label=status_label, message=error_msg, source="request")
                    if self._is_recoverable_openrouter_error(e, emitted_any=emitted_any) and idx < len(candidate_models) - 1:
                        log.warning("OpenRouter attempt failed for %s; trying fallback. %s", model_id, self._compact_error_headline(error_msg))
                        attempts.append((model_id, error_msg))
                        break
                    if retry_index < len(retry_delays) and self._is_recoverable_direct_provider_error(e, emitted_any=emitted_any):
                        delay = retry_delays[retry_index]
                        retry_index += 1
                        log.warning(
                            "Transient %s provider failure for %s; retrying attempt %d/%d after %.1fs. %s",
                            self.provider,
                            model_id,
                            retry_index,
                            len(retry_delays),
                            delay,
                            self._compact_error_headline(error_msg),
                        )
                        time.sleep(delay)
                        continue
                    if attempts:
                        attempts.append((model_id, error_msg))
                        error_msg = self._format_fallback_exhausted_error(attempts)
                    log.error(error_msg)
                    yield f"\n[Error: {error_msg}]\n"
                    return

    if self.provider == "local_file":
        try:
            llm = self.__class__._get_local_llm(self.model)
            flat_messages = []
            for message in messages:
                content = message.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(block.get("text", "") for block in content if block.get("type") == "text")
                flat_messages.append({"role": message["role"], "content": content})
            stream = llm.create_chat_completion(messages=flat_messages, stream=True)
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
    try:
        from core.local_embeddings import VoxLocalEmbedder
        embedder = VoxLocalEmbedder.get_instance()
        result = embedder.embed(texts)
        return result if result else []
    except Exception as e:
        log.error(f"Embedding failed: {e}")
        return []