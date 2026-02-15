package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"

	"vox-vector-engine/internal/engine"
	"vox-vector-engine/internal/index"
	"vox-vector-engine/internal/storage"
	"vox-vector-engine/internal/types"
)

func main() {
	var (
		cmd     = flag.String("cmd", "", "command to run: ingest_message | retrieve")
		dataDir = flag.String("data", "data", "data directory")
		dim     = flag.Int("dim", 768, "vector dimension")
		input   = flag.String("input", "", "JSON input payload (or use stdin if empty)")
	)
	flag.Parse()

	if *cmd == "" {
		log.Fatalf("error: -cmd is required")
	}

	// Setup components (same as server)
	if err := os.MkdirAll(*dataDir, 0755); err != nil {
		log.Fatalf("failed to create data dir: %v", err)
	}

	vecPath := filepath.Join(*dataDir, "vectors.bin")
	metaPath := filepath.Join(*dataDir, "metadata.db")

	vecs, err := storage.NewMmapVectorStore(vecPath, *dim)
	if err != nil {
		log.Fatalf("failed to open vector store: %v", err)
	}
	defer vecs.Close()

	meta, err := storage.NewBoltMetadataStore(metaPath)
	if err != nil {
		log.Fatalf("failed to open metadata store: %v", err)
	}
	defer meta.Close()

	idx := index.NewHnswIndex(vecs)

	// REBUILD INDEX: HNSW is in-memory only in this version.
	// To support CLI persistence, we must re-insert all existing vectors.
	count := vecs.Count()
	if count > 0 {
		for i := uint64(0); i < count; i++ {
			v, err := vecs.Get(i)
			if err == nil {
				idx.Add(i, v)
			}
		}
	}

	eng := engine.NewEngine(idx, vecs, meta)

	// Read input
	var inputBytes []byte
	if *input != "" {
		inputBytes = []byte(*input)
	} else {
		// Read from stdin
		stat, _ := os.Stdin.Stat()
		if stat != nil && (stat.Mode()&os.ModeCharDevice) == 0 {
			// Actually piped
			dec := json.NewDecoder(os.Stdin)
			var raw interface{}
			dec.Decode(&raw)
			inputBytes, _ = json.Marshal(raw)
		}
	}

	switch *cmd {
	case "ingest_message":
		var req struct {
			Namespace      string       `json:"namespace"`
			ConversationID string       `json:"conversation_id"`
			MessageID      string       `json:"message_id,omitempty"`
			Role           string       `json:"role"`
			Content        string       `json:"content"`
			Vector         types.Vector `json:"vector"`
			TokenCount     int          `json:"token_count"`
			Source         string       `json:"source,omitempty"`
		}
		if err := json.Unmarshal(inputBytes, &req); err != nil {
			log.Fatalf("json decode error: %v", err)
		}

		// Logic from server.go:HandleIngestMessage
		msgID := req.MessageID
		if msgID == "" {
			msgID = fmt.Sprintf("msg-%d", os.Getpid())
		}
		docID := fmt.Sprintf("chat:%s:%s", req.ConversationID, msgID)

		doc := types.Document{
			ID:     docID,
			Source: req.Source,
			Metadata: types.Metadata{
				"namespace":       req.Namespace,
				"conversation_id": req.ConversationID,
				"role":            req.Role,
			},
		}
		if err := meta.SaveDocument(doc); err != nil {
			log.Fatalf("save doc error: %v", err)
		}

		id, _ := vecs.Append(req.Vector)
		idx.Add(id, req.Vector)
		meta.SaveChunk(types.Chunk{
			ID: id, DocID: docID, Content: req.Content, TokenCount: req.TokenCount,
		})
		fmt.Printf("{\"status\":\"ok\",\"id\":%d}\n", id)

	case "retrieve":
		var req struct {
			Namespace string       `json:"namespace"`
			Query     types.Vector `json:"query"`
			MaxTokens int          `json:"max_tokens"`
		}
		if err := json.Unmarshal(inputBytes, &req); err != nil {
			log.Fatalf("json decode error: %v", err)
		}

		cfg := engine.RetrievalConfig{
			MaxTokens:        req.MaxTokens,
			Namespace:        req.Namespace,
			TopKCandidates:   40,  // ANN search depth
			SimilarityWeight: 0.7, // Default balance
			RecencyWeight:    0.3,
		}
		if req.MaxTokens > 40 {
			cfg.TopKCandidates = req.MaxTokens
		}
		res, _ := eng.Retrieve(req.Query, cfg)
		json.NewEncoder(os.Stdout).Encode(res)

	default:
		log.Fatalf("unknown command: %s", *cmd)
	}
}
