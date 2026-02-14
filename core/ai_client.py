from openai import OpenAI
from core.settings import SettingsManager
from core.prompts import SystemPrompts

class AIClient:
    def __init__(self):
        self.settings = SettingsManager()
        self.client = None
        self._setup_client()

    def _setup_client(self):
        # Determine provider based on selected model or settings
        # For simplicity in this version, we check if the key is OpenRouter or Local
        
        # In a real app, we might want a explicit "Provider" dropdown.
        # Here we infer: if model starts with "local/", use local URL. Else OpenRouter.
        pass

    def get_client(self, model_name):
        # 1. Parse Provider from Model Name "[Provider] Model"
        provider = "openrouter" # Default
        clean_model = model_name
        
        if model_name.startswith("["):
            try:
                end_idx = model_name.index("]")
                provider_tag = model_name[1:end_idx].lower()
                clean_model = model_name[end_idx+1:].strip()
                
                # Map tag to provider ID
                if "openai" in provider_tag: provider = "openai"
                elif "google" in provider_tag: provider = "google"
                elif "anthropic" in provider_tag: provider = "anthropic"
                elif "deepseek" in provider_tag: provider = "deepseek"
                elif "mistral" in provider_tag: provider = "mistral"
                elif "xai" in provider_tag: provider = "xai"
                elif "kimi" in provider_tag: provider = "kimi"
                elif "z.ai" in provider_tag or "zhipu" in provider_tag: provider = "zai"
                elif "openrouter" in provider_tag: provider = "openrouter"
                elif "local" in provider_tag: provider = "local"
            except:
                pass # Fallback
                
        # 2. Configure Client based on Provider
        api_key = self.settings.get_api_key(provider)
        base_url = None
        
        if provider == "openrouter":
            base_url = "https://openrouter.ai/api/v1"
            if not api_key: api_key = self.settings.get_openrouter_key() # Fallback
            
        elif provider == "local":
            base_url = self.settings.get_local_llm_url()
            api_key = "lm-studio"
            
        elif provider == "openai":
            # standard openai client
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
        
        # For OpenRouter, we need to pass the Referer header? 
        # OpenAI python client handles most things.
        
        return OpenAI(base_url=base_url, api_key=api_key), clean_model

    def stream_chat(self, messages, model_name):
        client, request_model = self.get_client(model_name)
        
        # Inject System Prompt if not present
        if messages and messages[0]["role"] != "system":
            messages.insert(0, {"role": "system", "content": SystemPrompts.CODING_AGENT})

        try:
            stream = client.chat.completions.create(
                model=request_model,
                messages=messages,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            yield f"\n[Error: {str(e)}]\n"

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
             
        if not api_key and provider != "local": return []

        req_url = ""
        headers = {}
        
        if provider == "openrouter":
            req_url = "https://openrouter.ai/api/v1/models"
        elif provider == "openai":
            req_url = "https://api.openai.com/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"}
        elif provider == "anthropic":
            # Anthropic doesn't have a public models endpoint easily accessible like OpenAI's simple list?
            # Actually they do: https://api.anthropic.com/v1/models (beta)
            # For now, let's return a hardcoded extended list or try to fetch if possible.
            # Let's mock a fetch for safety or return empty to rely on defaults.
            return [] 
        elif provider == "deepseek":
             req_url = "https://api.deepseek.com/models"
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
                    elif provider in ["openai", "deepseek"]:
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
                # Must start with gpt, o1, or chatgpt
                if not (lower_m.startswith("gpt") or lower_m.startswith("o1") or lower_m.startswith("chatgpt")):
                    continue
                # Exclude explicitly non-chat
                if any(x in lower_m for x in ["instruct", "realtime", "audio", "tts", "dall-e", "whisper", "embedding", "moderation", "babbage", "davinci"]):
                    continue
                    
            # OpenRouter Filters (heuristic, as they host many)
            elif provider == "openrouter":
                # Exclude known non-text/chat things if possible
                if any(x in lower_m for x in ["embedding", "moderation", "tts", "audio", "diffusion"]):
                    continue
            
            filtered.append(m)
            
        return filtered


