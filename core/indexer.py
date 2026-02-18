
import hashlib
import json
import os
import logging
from typing import List, Callable, Optional
from core.rag_client import RAGClient

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    '.py', '.go', '.js', '.ts', '.jsx', '.tsx', '.html', '.css',
    '.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.c', '.cpp',
    '.h', '.hpp', '.rs', '.java', '.kt', '.swift', '.rb', '.php'
}

IGNORED_DIRS = {
    '.git', '.vox', '.idea', '.vscode', '__pycache__', 'node_modules',
    'venv', 'env', 'dist', 'build', 'target', 'bin', 'obj',
    'storage', 'models',
}

MAX_FILE_SIZE = 512_000  # skip files > 500 KB


class ProjectIndexer:
    """Walks the project and ingests changed files into the RAG engine."""

    def __init__(self):
        self.rag = RAGClient()

    def _should_index(self, path: str) -> bool:
        if os.path.isdir(path):
            return os.path.basename(path) not in IGNORED_DIRS
        _, ext = os.path.splitext(path)
        return ext.lower() in ALLOWED_EXTENSIONS

    def _chunk_content(self, content: str, chunk_lines: int = 50, overlap: int = 10) -> List[tuple]:
        lines = content.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return []

        chunks = []
        start = 0
        while start < total_lines:
            end = min(start + chunk_lines, total_lines)
            chunk_text = "\n".join(lines[start:end])
            chunks.append((chunk_text, start + 1, end))
            if end == total_lines:
                break
            start += (chunk_lines - overlap)
        return chunks

    # ------------------------------------------------------------------
    # Hash manifest — tracks which files have already been indexed
    # ------------------------------------------------------------------
    @staticmethod
    def _manifest_path(root_path: str) -> str:
        return os.path.join(root_path, ".vox", "index_manifest.json")

    @staticmethod
    def _load_manifest(root_path: str) -> dict:
        p = ProjectIndexer._manifest_path(root_path)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @staticmethod
    def _save_manifest(root_path: str, manifest: dict):
        p = ProjectIndexer._manifest_path(root_path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(manifest, f)
        except Exception as e:
            log.warning("Could not save index manifest: %s", e)

    @staticmethod
    def _file_hash(path: str) -> str:
        h = hashlib.md5()
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
        except Exception:
            return ""
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Main index
    # ------------------------------------------------------------------
    def index_project(self, root_path: str, progress_callback: Optional[Callable[[int, int, str], None]] = None) -> bool:
        log.info("Starting project index for: %s", root_path)

        manifest = self._load_manifest(root_path)

        files_to_index = []
        for root, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in files:
                full_path = os.path.join(root, f)
                if self._should_index(full_path):
                    try:
                        if os.path.getsize(full_path) > MAX_FILE_SIZE:
                            continue
                    except OSError:
                        continue
                    files_to_index.append(full_path)

        # Filter to only changed files
        changed_files = []
        for fpath in files_to_index:
            rel = os.path.relpath(fpath, root_path)
            h = self._file_hash(fpath)
            if h and manifest.get(rel) == h:
                continue  # already indexed with same content
            changed_files.append((fpath, rel, h))

        total = len(changed_files)
        if total == 0:
            log.info("All %d files already indexed — nothing to do.", len(files_to_index))
            if progress_callback:
                progress_callback(100, 100, "Up to date")
            return True

        log.info("Indexing %d changed file(s) out of %d total.", total, len(files_to_index))

        processed = 0
        for fpath, rel_path, fhash in changed_files:
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                chunks = self._chunk_content(content)
                any_ok = False
                for chunk_text, start, end in chunks:
                    ok = self.rag.ingest_document(
                        file_path=rel_path,
                        content=chunk_text,
                        start_line=start,
                        end_line=end,
                    )
                    if ok:
                        any_ok = True
                # Only mark indexed if at least one chunk was actually stored
                if fhash and any_ok:
                    manifest[rel_path] = fhash
            except Exception as e:
                log.error("Failed to index %s: %s", rel_path, e)

            processed += 1
            if progress_callback:
                progress_callback(processed, total, f"Indexing {rel_path}")

        self._save_manifest(root_path, manifest)
        log.info("Indexing complete: %d file(s) processed.", processed)
        return True
