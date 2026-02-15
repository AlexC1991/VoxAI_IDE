
package main

import (
	"flag"
	"log"
	"net/http"
	"os"
	"path/filepath"

	"vox-vector-engine/internal/api"
	"vox-vector-engine/internal/engine"
	"vox-vector-engine/internal/index"
	"vox-vector-engine/internal/storage"
)

func main() {
	var (
		addr           = flag.String("addr", ":8080", "listen address")
		dataDir        = flag.String("data", "data", "data directory (vectors.bin, metadata.db)")
		dim            = flag.Int("dim", 1536, "vector dimension")
		maxElements    = flag.Int("max_elements", 200000, "HNSW max elements (unused; kept for CLI compat)")
		efSearch       = flag.Int("ef_search", 64, "HNSW ef_search (unused; kept for CLI compat)")
		efConstruction = flag.Int("ef_construction", 200, "HNSW ef_construction (unused; kept for CLI compat)")
		m              = flag.Int("m", 16, "HNSW M (unused; kept for CLI compat)")
	)
	_ = maxElements
	_ = efSearch
	_ = efConstruction
	_ = m

	flag.Parse()

	if err := os.MkdirAll(*dataDir, 0o755); err != nil {
		log.Fatalf("failed to create data dir: %v", err)
	}

	vecPath := filepath.Join(*dataDir, "vectors.bin")
	metaPath := filepath.Join(*dataDir, "metadata.db")

	vecs, err := storage.NewMmapVectorStore(vecPath, *dim)
	if err != nil {
		log.Fatalf("failed to open vector store: %v", err)
	}
	defer func() {
		if err := vecs.Close(); err != nil {
			log.Printf("vector store close error: %v", err)
		}
	}()

	meta, err := storage.NewBoltMetadataStore(metaPath)
	if err != nil {
		log.Fatalf("failed to open metadata store: %v", err)
	}
	defer func() {
		if err := meta.Close(); err != nil {
			log.Printf("metadata store close error: %v", err)
		}
	}()

	// In-memory ANN index (uses vecs as the vector source of truth).
	idx := index.NewHnswIndex(vecs)

	// Engine wires index + stores together (used by retrieval logic).
	eng := engine.NewEngine(idx, vecs, meta)

	srv := api.NewServer(eng, idx, meta, vecs)

	log.Printf("vox-vector-engine listening on %s (data=%s dim=%d)", *addr, *dataDir, *dim)
	if err := http.ListenAndServe(*addr, srv.Router()); err != nil {
		log.Fatalf("server failed: %v", err)
	}
}
