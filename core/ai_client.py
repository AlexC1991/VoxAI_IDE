
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
            return f"{local_url}/chat/completions" # Hope for the best or assume full URL?
            # Safer: specific logic for local
            
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
            system_msg = ""
            filtered_msgs = []
            
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    # Deep copy to avoid mutating original
                    new_m = m.copy()
                    
                    # Convert OpenAI multimodal format to Anthropic if needed
                    if isinstance(new_m["content"], list):
                        new_content = []
                        for block in new_m["content"]:
                            if block.get("type") == "image_url":
                                # Convert: image_url -> image source
                                url = block["image_url"]["url"]
                                if url.startswith("data:"):
                                    # Parse data:image/png;base64,.....
                                    try:
                                        header, data = url.split("base64,")
                                        # header is "data:image/png;"
                                        mime = header.replace("data:", "").replace(";", "")
                                        new_content.append({
                                            "type": "image",
                                            "source": {
                                                "type": "base64",
                                                "media_type": mime,
                                                "data": data
                                            }
                                        })
                                    except:
                                        pass # Malformed data uri?
                            else:
                                new_content.append(block)
                        new_m["content"] = new_content
                        
                    filtered_msgs.append(new_m)
            
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
                    response.raise_for_status()
                    
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
                                except:
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
                        except:
                            pass
                
                log.error(error_msg)
                yield f"\n[Error: {error_msg}]\n"

        if self.provider == "local_file":
            # GGUF Inference via llama-cpp-python
            try:
                from llama_cpp import Llama
                
                # Construct path
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                model_path = os.path.join(base_dir, "models", "llm", self.model)
                
                if not os.path.exists(model_path):
                    yield f"\n[Error: Model file not found at {model_path}]\n"
                    return

                # Hardware config (reuse from hardware.py or defaults)
                # For now, safe defaults or minimal config
                # TODO: Integrate with hardware.py for full acceleration
                
                log.info(f"Loading local model: {model_path}")
                # We should probably cache this instance in a singleton manager to avoid reload lag
                # For now, simple load per request (inefficient but works for proof of concept)
                
                llm = Llama(
                    model_path=model_path,
                    n_ctx=4096, # decent context
                    n_gpu_layers=-1, # Try to offload all to GPU if available (requires proper pip install)
                    verbose=True
                )
                
                # Format messages
                # Simple chat format or raw? Llama-cpp-python has create_chat_completion
                
                stream = llm.create_chat_completion(
                    messages=messages,
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
            # Use singleton instance to avoid reloading model
            embedder = VoxLocalEmbedder.get_instance()
            return embedder.embed(texts)
        except Exception as e:
            log.error(f"Embedding failed: {e}")
            return []
