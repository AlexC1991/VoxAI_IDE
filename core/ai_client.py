
import os
import requests
import json
import logging
from core.settings import SettingsManager

# Set up logging
log = logging.getLogger(__name__)

class AIClient:
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
        "Local": "local_file"
    }

    _llm_cache = {}  # class-level: {model_name: Llama instance}

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
        
        # Determine provider and model from selected model string
        # Formats:
        # 1. UI Format: "[Display Name] model_name" (e.g. "[OpenRouter] google/gemini-pro")
        # 2. Raw Format: "provider/model_name" (legacy or manual)
        full_model_name = self.settings_manager.get_selected_model()
        
        self.provider = "openai" # Default
        self.model = full_model_name
        
        import re
        # Check for UI format: [Provider] Model
        match = re.match(r"^\[(.*?)\]\s*(.*)$", full_model_name)
        if match:
            display_name = match.group(1)
            model_name = match.group(2)
            
            # Map display name to ID
            if display_name in self.DISPLAY_MAP:
                self.provider = self.DISPLAY_MAP[display_name]
                self.model = model_name
            else:
                # Unknown display name? Fallback to raw parsing of the whole string or just OpenRouter?
                # Best effort: treat display name as provider id if simple
                self.provider = display_name.lower()
                self.model = model_name
        
        elif "/" in full_model_name:
            # Raw format: provider/model
            self.provider, self.model = full_model_name.split("/", 1)
            
        else:
            # Check for [Local] prefix
            if full_model_name.startswith("[Local] "):
                self.provider = "local_file"
                self.model = full_model_name.replace("[Local] ", "")
            else:
                # No provider info found
                self.provider = "openai"
                self.model = full_model_name

        # Normalize provider
        self.provider = self.provider.lower()

        # Fallback for unknown providers -> OpenRouter
        if self.provider not in self.PROVIDER_CONFIG:
            # Only redirect if it wasn't already successfully mapped to 'local' or others
            # If we parsed "[MyCustomProvider] model", provider is "mycustomprovider".
            # We redirect to OpenRouter.
            # But we must ensure specific providers (like 'google' derived from 'Google Gemini') ARE in config.
            # They are.
            
            # For OpenRouter fallback, pass the original full model name if it was a slash split? 
            # Or the parsed model?
            # If I select "[OpenRouter] google/gemini-2.0", provider="openrouter", model="google/gemini-2.0". 
            # It IS in config. So this block is skipped.
            
            # If I select "unknown/model": provider="unknown", NOT in config.
            # Redirect to OpenRouter.
            self.model = full_model_name # Pass full name
            self.provider = "openrouter"

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

    def stream_chat(self, messages):
        """
        Yields chunks of text response from the AI provider.
        """
        url = self._get_url()
        headers = self._get_headers()
        config = self._get_config()
        fmt = config.get("format", "openai")
        
        payload = {}
        
        if fmt == "openai":
            # OpenAI / OpenRouter / DeepSeek / Mistral / etc.
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True
            }
            # OpenRouter quirk: if provider is openrouter, ensure model is full name?
            # In __init__, if we fell back to openrouter, we set self.model = full_model_name.
            # If we explicitly selected "openrouter/auto", self.model is "auto", which is correct for OR.
            
        elif fmt == "anthropic":
            # Anthropic Format
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
                "model": self.model,
                "messages": filtered_msgs,
                "stream": True,
                "max_tokens": 4096 
            }
            if system_msg:
                payload["system"] = system_msg

        if self.provider != "local_file":
            try:
                # log.debug(f"Sending request to {url} with model {self.model}")
                with requests.post(url, headers=headers, json=payload, stream=True) as response:
                    try:
                        response.raise_for_status()
                    except requests.exceptions.HTTPError as e:
                        try:
                            error_body = response.json()
                            if "error" in error_body:
                                if isinstance(error_body["error"], dict) and "message" in error_body["error"]:
                                    raise Exception(f"{e} - {error_body['error']['message']}") from e
                                raise Exception(f"{e} - {error_body['error']}") from e
                        except (json.JSONDecodeError, ValueError, KeyError):
                            pass
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
                                    
            except Exception as e:
                error_msg = f"AI Request Failed: {e}"
                if hasattr(e, "response") and e.response is not None:
                    if e.response.status_code == 402:
                         error_msg = "Provider Error: Insufficient Credits (402 Payment Required).\nPlease top up your OpenRouter/Provider balance."
                    else:
                        try:
                            error_body = e.response.text
                            log.error(f"API Error Body: {error_body}")
                            error_msg += f"\nServer Response: {error_body}"
                        except Exception:
                            pass
                
                log.error(error_msg)
                yield f"\n[Error: {error_msg}]\n"

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

            return sorted(model_ids)

        except Exception as e:
            log.error("Error fetching models for %s: %s", provider_id, e)
            if hasattr(e, "response") and e.response is not None:
                log.error("Response body: %s", e.response.text)
            return []
