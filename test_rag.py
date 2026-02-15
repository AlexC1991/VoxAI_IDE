
import os
import sys

# Add current dir to path
sys.path.append(os.getcwd())

from core.rag_client import RAGClient

def test_rag():
    rag = RAGClient()
    print(f"Storage Dir: {rag.storage_dir}")
    print(f"Namespace: {rag._project_namespace()}")
    
    test_word = "CrimsonLeopardFire"
    print(f"Ingesting test word: {test_word}...")
    success = rag.ingest_message("user", test_word, "test-conv-123")
    print(f"Ingestion success: {success}")
    
    if success:
        print("Waiting a moment for indexing...")
        import time
        time.sleep(2)
        
        print("Retrieving...")
        results = rag.retrieve("CrimsonLeopard", "[Vox Local] Native")
        print(f"Found {len(results)} results.")
        for i, res in enumerate(results):
            print(f"Result {i+1} [Score={res.score:.4f}]: {res.content}")

if __name__ == "__main__":
    test_rag()
