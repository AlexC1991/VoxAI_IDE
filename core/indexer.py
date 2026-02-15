
import os
import json
import uuid
import logging
from typing import List, Dict, Any, Optional

from core.settings import SettingsManager
from core.ai_client import AIClient
from core.rag_client import RAGClient

log = logging.getLogger(__name__)

class ProjectIndexer:
    """
    Handles walking the project directory, chunking files, 
    and ingesting them into the Vox_AISearch vector engine.
    """
    
    def __init__(self):
        self.settings = SettingsManager()
        self.ai = AIClient()
        self.rag = RAGClient()
        self.CHUNK_SIZE = 1000 # Chars, roughly 250-300 tokens
        self.CHUNK_OVERLAP = 200

    def index_project(self, root_path: str, progress_callback=None) -> bool:
        """
        Walks the project and ingests all text files.
        """
        if not os.path.isdir(root_path):
            log.error("Invalid project root: %s", root_path)
            return False

        namespace = self.rag._project_namespace()
        emb_model = self.settings.get_embedding_model()
        
        # Extensions to index
        valid_exts = {'.py', '.go', '.js', '.ts', '.c', '.cpp', '.h', '.hpp', '.md', '.txt', '.json', '.yaml', '.yml'}
        
        files_to_index = []
        for root, dirs, files in os.walk(root_path):
            # Ignore hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            if '__pycache__' in dirs: dirs.remove('__pycache__')
            
            for f in files:
                if any(f.endswith(ext) for ext in valid_exts):
                    files_to_index.append(os.path.join(root, f))

        total_files = len(files_to_index)
        log.info("Found %d files to index in %s", total_files, root_path)

        for i, file_path in enumerate(files_to_index):
            if progress_callback:
                progress_callback(i, total_files, os.path.basename(file_path))
            
            try:
                self._index_file(file_path, root_path, namespace, emb_model)
            except Exception as e:
                log.error("Failed to index %s: %s", file_path, e)

        return True

    def _index_file(self, file_path: str, root_path: str, namespace: str, emb_model: str):
        rel_path = os.path.relpath(file_path, root_path).replace("\\", "/")
        
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        if not content.strip():
            return

        chunks = self._chunk_text(content)
        if not chunks:
            return

        # Prepare for bulk embedding
        texts = [c['text'] for c in chunks]
        vectors = self.ai.embed_texts(texts, model_name=emb_model)

        doc_id = f"file:{rel_path}"
        
        # Construct IngestRequest
        ingest_chunks = []
        for idx, (chunk_data, vec) in enumerate(zip(chunks, vectors)):
            ingest_chunks.append({
                "doc_id": doc_id,
                "vector": vec,
                "content": chunk_data['text'],
                "start_line": chunk_data['start_line'],
                "end_line": chunk_data['end_line'],
                "token_count": 0 # Server can estimate or we can leave 0
            })

        payload = {
            "namespace": namespace,
            "document": {
                "id": doc_id,
                "source": "project_file",
                "metadata": {
                    "path": rel_path,
                    "filename": os.path.basename(file_path)
                }
            },
            "chunks": ingest_chunks
        }

        url = f"{self.rag.vector_engine_url}/ingest"
        self.rag._request_json("POST", url, payload)

    def _chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """Simple line-aware chunking."""
        lines = text.splitlines(keepends=True)
        chunks = []
        
        curr_text = ""
        start_line = 1
        
        for i, line in enumerate(lines):
            curr_text += line
            if len(curr_text) >= self.CHUNK_SIZE:
                end_line = i + 1
                chunks.append({
                    "text": curr_text,
                    "start_line": start_line,
                    "end_line": end_line
                })
                
                # Overlap: take last few lines
                overlap_lines = curr_text.splitlines()[-5:] # Heuristic overlap
                curr_text = "\n".join(overlap_lines) + "\n" if overlap_lines else ""
                start_line = end_line - len(overlap_lines) + 1
        
        # Final chunk
        if curr_text.strip():
            chunks.append({
                "text": curr_text,
                "start_line": start_line,
                "end_line": len(lines)
            })
            
        return chunks
