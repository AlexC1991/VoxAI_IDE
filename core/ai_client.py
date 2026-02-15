
from openai import OpenAI
from core.settings import SettingsManager
from core.prompts import SystemPrompts


class AIClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AIClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self.settings = SettingsManager()
        self.client = None
        # self._setup_client() # No longer auto-calling to avoid initialization bloat

    def _setup_client(self):
        # Kept for legacy; client instances are created per-request in get_client().
        pass

    def get_client(self, model_name):
        # 1. Parse Provider from Model Name "[Provider] Model"
        provider = "openrouter"  # Default
        clean_model = model_name

        if model_name.startswith("["):
            try:
                end_idx = model_name.index("]")
                provider_tag = model_name[1:end_idx].lower()
                clean_model = model_name[end_idx + 1 :].strip()

                # Map tag to provider ID
                if "openai" in provider_tag:
                    provider = "openai"
                elif "google" in provider_tag:
                    provider = "google"
                elif "anthropic" in provider_tag:
                    provider = "anthropic"
                elif "deepseek" in provider_tag:
                    provider = "deepseek"
                elif "mistral" in provider_tag:
                    provider = "mistral"
                elif "xai" in provider_tag:
                    provider = "xai"
                elif "kimi" in provider_tag:
                    provider = "kimi"
                elif "z.ai" in provider_tag or "zhipu" in provider_tag:
                    provider = "zai"
                elif "openrouter" in provider_tag:
                    provider = "openrouter"
                elif "local" in provider_tag:
                    provider = "local"
            except Exception:
                pass  # Fallback

        # 2. Configure Client based on Provider
        api_key = self.settings.get_api_key(provider)
        base_url = None

        if provider == "openrouter":
            base_url = "https://openrouter.ai/api/v1"
            if not api_key:
                api_key = self.settings.get_openrouter_key()  # Fallback

        elif provider == "local":
            # Local OpenAI-compatible server (LM Studio / llama.cpp server / etc.)
            base_url = self.settings.get_local_llm_url()
            api_key = api_key or "lm-studio"

        elif provider == "openai":
            # standard openai client (base_url None => default)
            pass

        elif provider == "google":
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

        elif provider == "deepseek":
            base_url = "https://api.deepseek.com"

        elif provider == "mistral":
            base_url = "https://api.mistral.ai/v1"

        elif provider == "xai":
            base_url = "https://api.x.ai/v1"

        # ... others ...

        return OpenAI(base_url=base_url, api_key=api_key), clean_model

    def stream_chat(self, messages, model_name):
        client, request_model = self.get_client(model_name)

        # Inject System Prompt if not present
        if messages and messages[0]["role"] != "system":
            messages.insert(0, {"role": "system", "content": SystemPrompts.CODING_AGENT})

        try:
            stream = client.chat.completions.create(model=request_model, messages=messages, stream=True)

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[Error: {str(e)}]\n"

    def embed_texts(self, texts, model_name):
        """
        Uses the same provider/model selection as chat, but calls the appropriate
        embeddings endpoint for that provider.
        """
        if isinstance(texts, str):
            texts = [texts]

        # 1. Parse Provider
        provider = "openrouter"
        clean_model = model_name
        if model_name.startswith("["):
            try:
                end_idx = model_name.index("]")
                provider = model_name[1:end_idx].lower()
                clean_model = model_name[end_idx + 1 :].strip()
            except: pass

        # 2. Hardwired VoxLocal Support (Truly Free RAG)
        # We always prioritize the native RIG driver for anything labeled "vox" or "local"
        if "vox" in provider or "local" in provider:
            from core.local_embeddings import VoxLocalEmbedder
            try:
                embedder = VoxLocalEmbedder.get_instance()
                vectors = embedder.embed(texts)
                if vectors:
                    return vectors
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"RIG local embedding failed: {e}")
                # If native RIG fails, we fall back to Google/OpenAI ONLY if keys exist,
                # but we STOP attempting to hit a local network port (Ollama/LM Studio)
                # to prevent the "target machine actively refused it" errors.
                pass

        # 3. Native Google Support
        if "google" in provider:
            import urllib.request
            import json
            api_key = self.settings.get_api_key("google")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:batchEmbedContents?key={api_key}"
            
            requests = []
            for t in texts:
                requests.append({
                    "model": f"models/{clean_model}",
                    "content": {"parts": [{"text": t}]}
                })
            
            payload = json.dumps({"requests": requests}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
                # Google returns { "embeddings": [ { "values": [...] } ] }
                return [item["values"] for item in data.get("embeddings", [])]

        # 3. Cloud Provider Support (OpenRouter, OpenAI, etc.)
        # This is only reached if NOT using local embeddings
        client, request_model = self.get_client(model_name)
        resp = client.embeddings.create(model=request_model, input=texts)

        vectors = []
        for item in resp.data:
            vectors.append(item.embedding)
        return vectors

    @staticmethod
    def fetch_openrouter_models(api_key=None):
        return AIClient.fetch_models("openrouter", api_key)

    @staticmethod
    def fetch_models(provider, api_key, url=None):
        """Fetches available models from the specified provider."""
        import urllib.request
        import json

        if not api_key and provider != "local":
            from core.settings import SettingsManager

            api_key = SettingsManager().get_api_key(provider)

        if not api_key and provider != "local":
            return []

        req_url = ""
        headers = {}

        if provider == "openrouter":
            req_url = "https://openrouter.ai/api/v1/models"
        elif provider == "openai":
            req_url = "https://api.openai.com/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"}
        elif provider == "anthropic":
            req_url = "https://api.anthropic.com/v1/models"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }
        elif provider == "google":
            # Google Gemini uses a query param for the key
            req_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        elif provider == "deepseek":
             req_url = "https://api.deepseek.com/models"
             headers = {"Authorization": f"Bearer {api_key}"}
        elif provider == "mistral":
             req_url = "https://api.mistral.ai/v1/models"
             headers = {"Authorization": f"Bearer {api_key}"}
        elif provider == "local":
             # Ollama style: GET /api/tags
             base = url or "http://localhost:11434"
             req_url = f"{base}/api/tags"
        
        if not req_url: return []

        try:
            req = urllib.request.Request(req_url, headers=headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    
                    if provider == "openrouter":
                        models = [item["id"] for item in data.get("data", [])]
                    elif provider in ["openai", "deepseek", "mistral"]:
                        models = [item["id"] for item in data.get("data", [])]
                    elif provider == "google":
                        # Google returns { "models": [ { "name": "models/gemini-pro" } ] }
                        models = [item["name"].replace("models/", "") for item in data.get("models", [])]
                    elif provider == "anthropic":
                        # Anthropic returns { "data": [ { "id": "..." } ] }
                        models = [item["id"] for item in data.get("data", [])]
                    elif provider == "local":
                        # Ollama returns { "models": [ { "name": "..." } ] }
                        models = [item["name"] for item in data.get("models", [])]
                    else:
                        models = []


                    # Filter for chat models only
                    models = AIClient._filter_chat_models(models, provider)

                    models.sort()
                    return models
                else:
                    print(f"[Error] {provider} API returned status: {response.status}")
                    return []
        except Exception as e:
            print(f"[Error] Failed to fetch {provider} models: {e}")
            return []

    @staticmethod
    def _filter_chat_models(models, provider):
        """Filters the list to include only likely chat models."""
        filtered = []
        for m in models:
            lower_m = m.lower()

            # OpenAI / General Filters
            if provider == "openai":
                if not (lower_m.startswith("gpt") or lower_m.startswith("o1") or lower_m.startswith("chatgpt")):
                    continue
                # Exclude explicitly non-chat
                if any(x in lower_m for x in ["instruct", "realtime", "audio", "tts", "dall-e", "whisper", "embedding", "moderation", "babbage", "davinci"]):
                    continue
            
            # Google Gemini Filters
            elif provider == "google":
                if "gemini" not in lower_m:
                    continue
                if any(x in lower_m for x in ["embedding", "aqa", "vision"]): # vision usually handled by chat now, but some specific vision-only models might exist
                    continue

            # Anthropic Filters
            elif provider == "anthropic":
                if "claude" not in lower_m:
                    continue

            # OpenRouter Filters (heuristic, as they host many)
            elif provider == "openrouter":
                # Exclude known non-text/chat things if possible
                if any(x in lower_m for x in ["embedding", "moderation", "tts", "audio", "diffusion"]):
                    continue
            
            filtered.append(m)


        return filtered
