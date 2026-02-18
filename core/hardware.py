import os
import psutil
import ctypes
import logging

log = logging.getLogger(__name__)

def get_hardware_config(api_root=None):
    """
    VoxAI Hardware Handshake (IDE Edition)
    Optimized for Ryzen APUs and High-Performance Backends.
    
    Args:
        api_root: Path to the VoxAI_Chat_API folder where DLLs reside.
    """
    log.info("--- Hardware Handshake Started ---")
    
    # 1. CPU Detection
    physical_cores = psutil.cpu_count(logical=False) or 4
    log.info(f"Detected {physical_cores} Physical Cores.")

    optimal_threads = physical_cores
    optimal_batch_threads = max(2, physical_cores // 2)

    # 2. Backend Search Path
    # Default to current project's Vox_RIG/drivers subdir if not provided
    if not api_root:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        api_root = os.path.join(base_dir, "Vox_RIG", "drivers")
    
    api_root = os.path.abspath(api_root)
    log.info(f"Scanning for drivers in: {api_root}")
    
    # 3. Apply Environment Optimizations (Ryzen APU / Vulkan)
    os.environ["GGML_NUMA"] = "0"
    os.environ["GGML_BACKEND_SEARCH_PATH"] = api_root
    
    llama_dll = os.path.join(api_root, "llama.dll")
    if os.path.exists(llama_dll):
        os.environ["LLAMA_CPP_LIB"] = llama_dll
        log.info(f"Using local LLAMA library: {llama_dll}")

    # Default Mode: APU (Vulkan Hybrid)
    mode = "APU (Hybrid/Vulkan)"
    config = {
        "n_gpu_layers": 26,           
        "n_threads": optimal_threads, 
        "n_threads_batch": optimal_batch_threads, 
        "n_batch": 512,
        "flash_attn": True,
        "use_mlock": True,            
        "busy_wait": "1",             
        "cache_type_k": "f16",
        "cache_type_v": "f16"
    }

    # 4. Check for Unleashed Mode (CUDA/ZLUDA)
    cuda_dll = os.path.join(api_root, "ggml-cuda.dll")
    if os.path.exists(cuda_dll):
        try:
            ctypes.CDLL(cuda_dll)
            mode = "UNLEASHED (CUDA/ZLUDA)"
            config.update({
                "n_gpu_layers": -1,       
                "n_threads": 4,           
                "n_threads_batch": 4,     
                "n_batch": 1024,          
                "use_mlock": False,       
                "busy_wait": "0"          
            })
            log.info("High-Performance Driver (CUDA/ZLUDA) Loaded.")
        except OSError:
            log.warning("CUDA Driver found but failed to load. Staying on APU.")

    os.environ["GGML_VK_FORCE_BUSY_WAIT"] = config["busy_wait"]
    log.info(f"Final Mode: {mode}")
    log.info("--- Hardware Handshake Complete ---")
    
    return mode, config, api_root
