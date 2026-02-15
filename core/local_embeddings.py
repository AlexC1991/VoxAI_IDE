import os
import logging
import threading
from core.hardware import get_hardware_config

log = logging.getLogger(__name__)

class VoxLocalEmbedder:
    _instance = None
    _model_path = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, model_path=None):
        with cls._lock:
            if cls._instance is None or cls._model_path != model_path:
                cls._instance = cls(model_path)
                cls._model_path = model_path
            return cls._instance

    def __init__(self, model_path=None):
        self.llm = None
        self.config = None
        self.api_root = None
        self._initialize_engine(model_path)

    def _initialize_engine(self, model_path):
        try:
            from llama_cpp import Llama
        except ImportError:
            log.error("llama-cpp-python not installed. Local RAG disabled.")
            return

        # 1. Run Hardware Handshake
        mode, self.config, self.api_root = get_hardware_config()
        
        if not model_path:
            # Fallback: look for ANY gguf in the vox rig models dir
            models_dir = os.path.join(os.path.dirname(self.api_root), "models")
            if os.path.exists(models_dir):
                files = [f for f in os.listdir(models_dir) if f.endswith(".gguf")]
                if files:
                    model_path = os.path.join(models_dir, files[0])
            
        if not model_path or not os.path.exists(model_path):
            log.warning(f"No local embedding model found at: {model_path}")
            return

        log.info(f"Initializing VoxLocal Engine ({mode}) with model: {model_path}")
        
        try:
            self.llm = Llama(
                model_path=model_path,
                n_ctx=2048,
                embedding=True, # CRITICAL for RAG
                
                # INJECTING GOLDEN CONFIG
                n_gpu_layers=self.config['n_gpu_layers'],
                n_threads=self.config['n_threads'],
                n_threads_batch=self.config['n_threads_batch'],
                n_batch=self.config['n_batch'],
                flash_attn=self.config['flash_attn'],
                use_mlock=self.config['use_mlock'],
                cache_type_k=self.config['cache_type_k'],
                cache_type_v=self.config['cache_type_v'],
                verbose=False
            )
            log.info("VoxLocal Engine Online.")
        except Exception as e:
            log.error(f"Failed to load VoxLocal Engine: {e}")

    def embed(self, texts):
        if not self.llm:
            return None
        
        if isinstance(texts, str):
            texts = [texts]
            
        vectors = []
        with self._lock:
            for text in texts:
                # llama_cpp returns a list of floats for each text
                vector = self.llm.embed(text)
                vectors.append(vector)
            
        return vectors
