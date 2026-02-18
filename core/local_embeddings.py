
import os
import logging
import threading
import contextlib
import numpy as np
from core.hardware import get_hardware_config

log = logging.getLogger(__name__)

@contextlib.contextmanager
def suppress_c_output():
    """
    Redirects C-level stdout/stderr to devnull to silence llama.cpp init spam.
    Each fd operation is individually guarded so a partial failure won't break I/O.
    """
    null_fd = None
    save_stdout_fd = None
    save_stderr_fd = None
    try:
        null_fd = os.open(os.devnull, os.O_RDWR)
        save_stdout_fd = os.dup(1)
        save_stderr_fd = os.dup(2)
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)
    except OSError:
        pass

    try:
        yield
    finally:
        try:
            if save_stdout_fd is not None:
                os.dup2(save_stdout_fd, 1)
            if save_stderr_fd is not None:
                os.dup2(save_stderr_fd, 2)
        except OSError:
            pass
        for fd in (null_fd, save_stdout_fd, save_stderr_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

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
            print("ERROR: llama-cpp-python not installed. Run 'pip install llama-cpp-python'")
            return

        # 1. Run Hardware Handshake
        mode, self.config, self.api_root = get_hardware_config()
        
        # 2. Determine Model Path
        if not model_path:
            vox_rig_dir = os.path.dirname(self.api_root)
            default_model = os.path.join(vox_rig_dir, "models", "nomic-embed-text.gguf")
            
            if os.path.exists(default_model):
                model_path = default_model
            else:
                models_dir = os.path.join(vox_rig_dir, "models")
                if os.path.exists(models_dir):
                    files = [f for f in os.listdir(models_dir) if f.endswith(".gguf")]
                    if files:
                        model_path = os.path.join(models_dir, files[0])
            
        if not model_path or not os.path.exists(model_path):
            log.warning(f"No local embedding model found at: {model_path}")
            return

        log.info(f"Initializing VoxLocal Engine ({mode}) with model: {model_path}")
        
        try:
            with suppress_c_output():
                self.llm = Llama(
                    model_path=model_path,
                    n_ctx=2048,
                    embedding=True,
                    n_gpu_layers=self.config['n_gpu_layers'],
                    n_threads=self.config['n_threads'],
                    n_threads_batch=self.config['n_threads_batch'],
                    n_batch=self.config['n_batch'],
                    flash_attn=self.config['flash_attn'],
                    use_mlock=self.config['use_mlock'],
                    cache_type_k=self.config['cache_type_k'],
                    cache_type_v=self.config['cache_type_v'],
                    verbose=False,
                )
            log.info("VoxLocal Engine Online.")
        except Exception as e:
            log.error(f"Failed to load VoxLocal Engine: {e}")

    def embed(self, texts):
        if not self.llm:
            log.warning("Embed called but no model loaded.")
            return None
        
        if isinstance(texts, str):
            texts = [texts]

        log.debug("Embedding %d text(s) (total %d chars)", len(texts), sum(len(t) for t in texts))
        vectors = []
        with self._lock:
            with suppress_c_output():
                for text in texts:
                    try:
                        vector = self.llm.embed(text)
                        
                        if vector and isinstance(vector[0], list):
                            vector = vector[0]
                        
                        v_np = np.array(vector, dtype=np.float32)
                        norm = np.linalg.norm(v_np)
                        if norm > 0:
                            v_np = v_np / norm
                        vector = v_np.tolist()
                            
                        vectors.append(vector)
                    except Exception as e:
                        log.error(f"Embedding failed for text fragment: {e}")

        log.debug("Embedding complete: %d vectors produced (dim=%d)",
                  len(vectors), len(vectors[0]) if vectors else 0)
        return vectors
