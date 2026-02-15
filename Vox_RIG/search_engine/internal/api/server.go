
package api

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"

	"vox-vector-engine/internal/engine"
	"vox-vector-engine/internal/index"
	"vox-vector-engine/internal/storage"
	"vox-vector-engine/internal/types"
)

type Server struct {
	engine *engine.Engine
	index  *index.HnswIndex
	meta   *storage.BoltMetadataStore
	vecs   storage.VectorStore
}

func NewServer(e *engine.Engine, idx *index.HnswIndex, meta *storage.BoltMetadataStore, vecs storage.VectorStore) *Server {
	return &Server{
		engine: e,
		index:  idx,
		meta:   meta,
		vecs:   vecs,
	}
}

// IngestChunk is used only for receiving data via API
type IngestChunk struct {
	DocID      string       `json:"doc_id"`
	Vector     types.Vector `json:"vector"`
	Content    string       `json:"content"`
	StartLine  int          `json:"start_line"`
	EndLine    int          `json:"end_line"`
	TokenCount int          `json:"token_count"`
}

type IngestRequest struct {
	// Namespace is an optional logical partition. If set, it will be copied into
	// Document.Metadata["namespace"] unless already present.
	Namespace string         `json:"namespace,omitempty"`
	Document  types.Document `json:"document"`
	Chunks    []IngestChunk  `json:"chunks"`
}

type RetrieveRequest struct {
	// Namespace: if provided, only returns chunks whose Document.Metadata["namespace"] matches.
	Namespace string       `json:"namespace,omitempty"`
	Query     types.Vector `json:"query"`
	MaxTokens int          `json:"max_tokens"`
}

// IngestMessageRequest is a convenience endpoint for chat/memory style ingestion.
// It ingests exactly one chunk (the message content) and stores namespace + conversation
// metadata on the Document.
//
// Recommended IDs:
// - namespace: stable project/workspace id (e.g. repo path hash, workspace UUID)
// - conversation_id: stable chat/thread id
type IngestMessageRequest struct {
	Namespace      string       `json:"namespace"`
	ConversationID string       `json:"conversation_id"`
	MessageID      string       `json:"message_id,omitempty"` // optional; if empty server generates
	Role           string       `json:"role"`                 // "user" | "assistant" | "system"
	Content        string       `json:"content"`
	Vector         types.Vector `json:"vector"`
	TokenCount     int          `json:"token_count"`
	TimestampUTC   string       `json:"timestamp_utc,omitempty"` // optional RFC3339; if empty server uses now
	Source         string       `json:"source,omitempty"`        // optional; default "chat"
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func (s *Server) HandleRoot(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"service":    "vox-vector-engine",
		"ok":         true,
		"time_utc":   time.Now().UTC().Format(time.RFC3339),
		"endpoints":  []string{"/health", "/stats", "/ingest", "/ingest_message", "/retrieve", "/reset"},
		"api_schema": 1,
	})
}

func (s *Server) HandleHealth(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":        true,
		"time_utc":  time.Now().UTC().Format(time.RFC3339),
		"vec_count": s.vecs.Count(),
	})
}

func (s *Server) HandleStats(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"vec_count": s.vecs.Count(),
	})
}

type resetResponse struct {
	Status string `json:"status"`
}

func (s *Server) HandleReset(w http.ResponseWriter, r *http.Request) {
	// Resets the in-memory ANN index only (does not delete on-disk vectors/metadata).
	// Intended for dev/test. Production should isolate via namespaces.
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	s.index.Reset()
	writeJSON(w, http.StatusOK, resetResponse{Status: "reset_ok"})
}

func (s *Server) HandleIngest(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req IngestRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	// Apply namespace to document metadata if provided.
	if req.Namespace != "" {
		if req.Document.Metadata == nil {
			req.Document.Metadata = types.Metadata{}
		}
		if _, exists := req.Document.Metadata["namespace"]; !exists {
			req.Document.Metadata["namespace"] = req.Namespace
		}
	}

	log.Printf("[ingest] doc_id=%s source=%s chunks=%d namespace=%v",
		req.Document.ID, req.Document.Source, len(req.Chunks), req.Document.Metadata["namespace"])

	if err := s.meta.SaveDocument(req.Document); err != nil {
		log.Printf("[ingest] failed saving document id=%s: %v", req.Document.ID, err)
		http.Error(w, "Failed to save document", http.StatusInternalServerError)
		return
	}

	ingestedIDs := make([]uint64, 0, len(req.Chunks))

	for _, ic := range req.Chunks {
		id, err := s.vecs.Append(ic.Vector)
		if err != nil {
			log.Printf("[ingest] failed append vector doc_id=%s: %v", ic.DocID, err)
			http.Error(w, "Failed to append vector", http.StatusInternalServerError)
			return
		}

		chunk := types.Chunk{
			ID:         id,
			DocID:      ic.DocID,
			Content:    ic.Content,
			StartLine:  ic.StartLine,
			EndLine:    ic.EndLine,
			TokenCount: ic.TokenCount,
		}

		s.index.Add(id, ic.Vector)

		if err := s.meta.SaveChunk(chunk); err != nil {
			log.Printf("[ingest] failed save chunk metadata id=%d doc_id=%s: %v", id, ic.DocID, err)
			http.Error(w, "Failed to save chunk metadata", http.StatusInternalServerError)
			return
		}

		ingestedIDs = append(ingestedIDs, id)
	}

	log.Printf("[ingest] ok doc_id=%s ingested=%d vec_count=%d", req.Document.ID, len(ingestedIDs), s.vecs.Count())

	writeJSON(w, http.StatusOK, map[string]any{
		"status":       "ingested",
		"doc_id":       req.Document.ID,
		"chunk_ids":    ingestedIDs,
		"vector_count": s.vecs.Count(),
	})
}

func (s *Server) HandleIngestMessage(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req IngestMessageRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if req.Namespace == "" {
		http.Error(w, "namespace is required", http.StatusBadRequest)
		return
	}
	if req.ConversationID == "" {
		http.Error(w, "conversation_id is required", http.StatusBadRequest)
		return
	}
	if req.Role == "" {
		http.Error(w, "role is required", http.StatusBadRequest)
		return
	}
	if req.Content == "" {
		http.Error(w, "content is required", http.StatusBadRequest)
		return
	}
	if len(req.Vector) == 0 {
		http.Error(w, "vector is required", http.StatusBadRequest)
		return
	}

	ts := time.Now().UTC()
	if req.TimestampUTC != "" {
		parsed, err := time.Parse(time.RFC3339, req.TimestampUTC)
		if err != nil {
			http.Error(w, "timestamp_utc must be RFC3339", http.StatusBadRequest)
			return
		}
		ts = parsed.UTC()
	}

	source := req.Source
	if source == "" {
		source = "chat"
	}

	msgID := req.MessageID
	if msgID == "" {
		// time-based id; caller can also supply a stable UUID.
		msgID = fmt.Sprintf("msg-%d", time.Now().UTC().UnixNano())
	}

	// One message == one document + one chunk.
	// DocID is stable across retries if message_id is stable.
	docID := fmt.Sprintf("chat:%s:%s", req.ConversationID, msgID)

	doc := types.Document{
		ID:        docID,
		Source:    source,
		Timestamp: ts,
		Metadata: types.Metadata{
			"namespace":       req.Namespace,
			"conversation_id": req.ConversationID,
			"message_id":      msgID,
			"role":            req.Role,
			"type":            "chat_message",
		},
	}

	log.Printf("[ingest_message] start namespace=%s conversation_id=%s message_id=%s role=%s",
		req.Namespace, req.ConversationID, msgID, req.Role)

	if err := s.meta.SaveDocument(doc); err != nil {
		log.Printf("[ingest_message] failed saving document id=%s: %v", doc.ID, err)
		http.Error(w, "Failed to save document", http.StatusInternalServerError)
		return
	}

	vecID, err := s.vecs.Append(req.Vector)
	if err != nil {
		log.Printf("[ingest_message] failed append vector doc_id=%s: %v", doc.ID, err)
		http.Error(w, "Failed to append vector", http.StatusInternalServerError)
		return
	}

	chunk := types.Chunk{
		ID:         vecID,
		DocID:      doc.ID,
		Content:    req.Content,
		StartLine:  0,
		EndLine:    0,
		TokenCount: req.TokenCount,
	}

	s.index.Add(vecID, req.Vector)

	if err := s.meta.SaveChunk(chunk); err != nil {
		log.Printf("[ingest_message] failed save chunk metadata id=%d doc_id=%s: %v", vecID, doc.ID, err)
		http.Error(w, "Failed to save chunk metadata", http.StatusInternalServerError)
		return
	}

	log.Printf("[ingest_message] ok doc_id=%s chunk_id=%d vec_count=%d", doc.ID, vecID, s.vecs.Count())

	writeJSON(w, http.StatusOK, map[string]any{
		"status":         "ingested_message",
		"doc_id":         doc.ID,
		"chunk_id":       vecID,
		"vector_count":   s.vecs.Count(),
		"message_id":     msgID,
		"conversation_id": req.ConversationID,
		"namespace":      req.Namespace,
	})
}

func (s *Server) HandleRetrieve(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req RetrieveRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if len(req.Query) == 0 {
		http.Error(w, "query vector is required", http.StatusBadRequest)
		return
	}
	if req.MaxTokens <= 0 {
		req.MaxTokens = 2000
	}

	cfg := engine.RetrievalConfig{
		MaxTokens:        req.MaxTokens,
		SimilarityWeight: 0.8,
		RecencyWeight:    0.2,
		TopKCandidates:   50,
		Namespace:        req.Namespace,
	}

	res, err := s.engine.Retrieve(req.Query, cfg)
	if err != nil {
		http.Error(w, "retrieval failed", http.StatusInternalServerError)
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"chunks":       res.Chunks,
		"total_tokens": res.TotalTokens,
		"truncated":    res.Truncated,
	})
}

func (s *Server) Router() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.HandleRoot)
	mux.HandleFunc("/health", s.HandleHealth)
	mux.HandleFunc("/stats", s.HandleStats)
	mux.HandleFunc("/reset", s.HandleReset)
	mux.HandleFunc("/ingest", s.HandleIngest)
	mux.HandleFunc("/ingest_message", s.HandleIngestMessage)
	mux.HandleFunc("/retrieve", s.HandleRetrieve)
	return mux
}

func (s *Server) Start(addr string) error {
	log.Printf("API server listening on %s", addr)
	return http.ListenAndServe(addr, s.Router())
}
