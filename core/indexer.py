
import os
import logging
from typing import List, Callable, Optional
from core.rag_client import RAGClient

log = logging.getLogger(__name__)

# Extensions to index
ALLOWED_EXTENSIONS = {
    '.py', '.go', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', 
    '.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.c', '.cpp', 
    '.h', '.hpp', '.rs', '.java', '.kt', '.swift', '.rb', '.php'
}

# Dirs to ignore
IGNORED_DIRS = {
    '.git', '.vox', '.idea', '.vscode', '__pycache__', 'node_modules', 
    'venv', 'env', 'dist', 'build', 'target', 'bin', 'obj'
}

class ProjectIndexer:
    """
    Handles walking the project directory and ingesting files into the RAG engine.
    """
    
    def __init__(self):
        self.rag = RAGClient()

    def _should_index(self, path: str) -> bool:
        if os.path.isdir(path):
            return os.path.basename(path) not in IGNORED_DIRS
        
        # Check file extension
        _, ext = os.path.splitext(path)
        return ext.lower() in ALLOWED_EXTENSIONS

    def _chunk_content(self, content: str, chunk_lines: int = 50, overlap: int = 10) -> List[tuple[str, int, int]]:
        """
        Splits content into overlapping chunks of lines.
        Returns list of (chunk_text, start_line, end_line).
        """
        lines = content.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return []
            
        chunks = []
        start = 0
        while start < total_lines:
            end = min(start + chunk_lines, total_lines)
            chunk_text = "\n".join(lines[start:end])
            
            # 1-based line numbers for user reference
            chunks.append((chunk_text, start + 1, end))
            
            if end == total_lines:
                break
                
            start += (chunk_lines - overlap)
            
        return chunks

    def index_project(self, root_path: str, progress_callback: Optional[Callable[[int, int, str], None]] = None) -> bool:
        """
        Walks the project and ingests all text files.
        """
        log.info(f"Starting project index for: {root_path}")
        
        files_to_index = []
        for root, dirs, files in os.walk(root_path):
            # Prune ignored dirs
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            
            for f in files:
                full_path = os.path.join(root, f)
                if self._should_index(full_path):
                    files_to_index.append(full_path)

        total_files = len(files_to_index)
        if total_files == 0:
            log.info("No files found to index.")
            if progress_callback:
                progress_callback(100, 100, "No files found")
            return True

        processed = 0
        for fpath in files_to_index:
            rel_path = os.path.relpath(fpath, root_path)
            
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Simple chunking strategy
                chunks = self._chunk_content(content)
                
                for chunk_text, start, end in chunks:
                    self.rag.ingest_document(
                        file_path=rel_path,
                        content=chunk_text,
                        start_line=start,
                        end_line=end
                    )
            except Exception as e:
                log.error(f"Failed to index {rel_path}: {e}")
            
            processed += 1
            if progress_callback:
                progress_callback(processed, total_files, f"Indexing {rel_path}")

        log.info(f"Completed indexing {processed} files.")
        return True
