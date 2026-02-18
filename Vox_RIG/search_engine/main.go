// Unified entry point for vox-vector-engine.
// If -cmd is set, runs a single CLI command and exits.
// Otherwise, starts the HTTP server on -addr.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"vox-vector-engine/internal/api"
	"vox-vector-engine/internal/engine"
	"vox-vector-engine/internal/index"
	"vox-vector-engine/internal/storage"
	"vox-vector-engine/internal/types"
)

func main() {
	var (
		addr    = flag.String("addr", "", "listen address (e.g. 127.0.0.1:8080). If empty and -cmd is empty, defaults to :8080")
		cmd     = flag.String("cmd", "", "CLI command: ingest_message | ingest_document | retrieve")
		dataDir = flag.String("data", "data", "data directory for vectors.bin and metadata.db")
		dim     = flag.Int("dim", 768, "vector dimension")
		input   = flag.String("input", "", "JSON input payload for CLI mode (or pipe via stdin)")
	)
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
	defer vecs.Close()

	meta, err := storage.NewBoltMetadataStore(metaPath)
	if err != nil {
		log.Fatalf("failed to open metadata store: %v", err)
	}
	defer meta.Close()

	if *cmd != "" {
		runCLI(*cmd, *input, vecs, meta, *dim)
		return
	}

	// ── HTTP server mode ──
	listenAddr := *addr
	if listenAddr == "" {
		listenAddr = ":8080"
	}

	idx := index.NewHnswIndex(vecs)
	eng := engine.NewEngine(idx, vecs, meta)
	srv := api.NewServer(eng, idx, meta, vecs)

	log.Printf("vox-vector-engine listening on %s (data=%s dim=%d)", listenAddr, *dataDir, *dim)
	if err := http.ListenAndServe(listenAddr, srv.Router()); err != nil {
		log.Fatalf("server failed: %v", err)
	}
}

// runCLI handles single-shot CLI commands then exits.
func runCLI(cmd, rawInput string, vecs *storage.MmapVectorStore, meta *storage.BoltMetadataStore, dim int) {
	var inputBytes []byte
	if rawInput != "" {
		inputBytes = []byte(rawInput)
	} else {
		stat, _ := os.Stdin.Stat()
		if stat != nil && (stat.Mode()&os.ModeCharDevice) == 0 {
			dec := json.NewDecoder(os.Stdin)
			var raw interface{}
			dec.Decode(&raw)
			inputBytes, _ = json.Marshal(raw)
		}
	}

	switch cmd {
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

		msgID := req.MessageID
		if msgID == "" {
			msgID = fmt.Sprintf("msg-%d", os.Getpid())
		}
		docID := fmt.Sprintf("chat:%s:%s", req.ConversationID, msgID)

		doc := types.Document{
			ID:        docID,
			Source:    req.Source,
			Timestamp: time.Now(),
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
		meta.SaveChunk(types.Chunk{
			ID: id, DocID: docID, Content: req.Content, TokenCount: req.TokenCount,
		})
		fmt.Printf("{\"status\":\"ok\",\"id\":%d}\n", id)

	case "ingest_document":
		var req struct {
			Namespace  string       `json:"namespace"`
			FilePath   string       `json:"file_path"`
			Content    string       `json:"content"`
			Vector     types.Vector `json:"vector"`
			TokenCount int          `json:"token_count"`
			StartLine  int          `json:"start_line"`
			EndLine    int          `json:"end_line"`
		}
		if err := json.Unmarshal(inputBytes, &req); err != nil {
			log.Fatalf("json decode error: %v", err)
		}

		docID := fmt.Sprintf("file:%s:%s:%d-%d", req.Namespace, req.FilePath, req.StartLine, req.EndLine)

		doc := types.Document{
			ID:        docID,
			Source:    req.FilePath,
			Timestamp: time.Now(),
			Metadata: types.Metadata{
				"namespace": req.Namespace,
				"file_path": req.FilePath,
				"type":      "code",
			},
		}
		if err := meta.SaveDocument(doc); err != nil {
			log.Fatalf("save doc error: %v", err)
		}

		id, _ := vecs.Append(req.Vector)
		meta.SaveChunk(types.Chunk{
			ID:         id,
			DocID:      docID,
			Content:    req.Content,
			TokenCount: req.TokenCount,
			StartLine:  req.StartLine,
			EndLine:    req.EndLine,
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

		idx := index.NewHnswIndex(vecs)
		count := vecs.Count()
		for i := uint64(0); i < count; i++ {
			v, err := vecs.Get(i)
			if err == nil {
				idx.Add(i, v)
			}
		}
		eng := engine.NewEngine(idx, vecs, meta)

		cfg := engine.RetrievalConfig{
			MaxTokens:        req.MaxTokens,
			Namespace:        req.Namespace,
			TopKCandidates:   50,
			SimilarityWeight: 0.7,
			RecencyWeight:    0.3,
		}
		res, _ := eng.Retrieve(req.Query, cfg)
		json.NewEncoder(os.Stdout).Encode(res)

	default:
		log.Fatalf("unknown command: %s", cmd)
	}
}
