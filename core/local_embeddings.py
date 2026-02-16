
import os
import sys
import logging
import threading
import contextlib
import numpy as np
from core.hardware import get_hardware_config

log = logging.getLogger(__name__)

@contextlib.contextmanager
def suppress_c_output():
    """
    Redirects C-level stdout and stderr to os.devnull.
    Useful for silencing noisy C/C++ libraries like llama.cpp.
    """
    try:
        # Open the null device
        null_fd = os.open(os.devnull, os.O_RDWR)
        
        # Save original file descriptors
        save_stdout_fd = os.dup(1)
        save_stderr_fd = os.dup(2)
        
        # Redirect stdout and stderr to null
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)
        
        yield
        
    except Exception:
        # If anything goes wrong, yield anyway so app doesn't crash
        yield
        
    finally:
        # Restore safe fds
        try:
            os.dup2(save_stdout_fd, 1)
            os.dup2(save_stderr_fd, 2)
            
            os.close(null_fd)
            os.close(save_stdout_fd)
            os.close(save_stderr_fd)
        except:
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
            # Removed suppress_c_output for Windows stability
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
                verbose=False # Still set this
            )
            log.info("VoxLocal Engine Online.")
        except Exception as e:
            log.error(f"Failed to load VoxLocal Engine: {e}")
            print(f"VoxLocal Engine Load Error: {e}")

    def embed(self, texts):
        if not self.llm:
            return None
        
        if isinstance(texts, str):
            texts = [texts]
            
        vectors = []
        with self._lock:
            # Removed suppress_c_output for Windows stability
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
            
        return vectors
