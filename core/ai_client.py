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
        api_key = self.settings.get_openrouter_key()
        base_url = "https://openrouter.ai/api/v1"
        
        if model_name.startswith("local/"):
            base_url = self.settings.get_local_llm_url()
            api_key = "lm-studio" # Local usually ignores keys, but needs a string
        
        return OpenAI(base_url=base_url, api_key=api_key)

    def stream_chat(self, messages, model_name):
        client = self.get_client(model_name)
        
        # Clean model name if needed (remove 'local/' prefix if the local server doesn't expect it)
        # But usually local servers ignore model name or expect specific ones.
        # Let's clean "local/" prefix for actual request
        request_model = model_name.replace("local/", "")
        
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
    def fetch_openrouter_models():
        """Fetches available models from OpenRouter API."""
        import urllib.request
        import json
        
        url = "https://openrouter.ai/api/v1/models"
        try:
            with urllib.request.urlopen(url) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    # Extract IDs
                    # API returns { "data": [ { "id": "...", "name": "..." }, ... ] }
                    models = [item["id"] for item in data.get("data", [])]
                    models.sort()
                    return models
                else:
                    print(f"[Error] OpenRouter API returned status: {response.status}")
                    return []
        except Exception as e:
            print(f"[Error] Failed to fetch OpenRouter models: {e}")
            return []
