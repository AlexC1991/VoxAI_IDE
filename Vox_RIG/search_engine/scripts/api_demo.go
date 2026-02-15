
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

const baseURL = "http://localhost:8080"

type vector []float32

type document struct {
	ID        string            `json:"id"`
	Source    string            `json:"source"`
	Timestamp time.Time         `json:"timestamp"`
	Metadata  map[string]string `json:"metadata"`
}

type ingestChunk struct {
	DocID      string `json:"doc_id"`
	Vector     vector `json:"vector"`
	Content    string `json:"content"`
	StartLine  int    `json:"start_line"`
	EndLine    int    `json:"end_line"`
	TokenCount int    `json:"token_count"`
}

type ingestRequest struct {
	Namespace string      `json:"namespace,omitempty"`
	Document  document    `json:"document"`
	Chunks    []ingestChunk `json:"chunks"`
}

type retrieveRequest struct {
	Namespace string `json:"namespace,omitempty"`
	Query     vector `json:"query"`
	MaxTokens int    `json:"max_tokens"`
}

func main() {
	// This demo simulates "chat memory":
	// - Ingest a few messages under a namespace (project/workspace)
	// - Query with an embedding (dummy vector here)
	// Your IDE would generate real embeddings and use the same namespace every time.
	namespace := "demo-project-123"

	// Create a trivial vector (must match engine dimensionality; demo assumes 1536 like tests)
	dim := 1536
	makeVec := func(x float32) vector {
		v := make(vector, dim)
		v[0] = x
		return v
	}

	now := time.Now().UTC()
	docID := fmt.Sprintf("chat-%d", now.UnixNano())

	req := ingestRequest{
		Namespace: namespace,
		Document: document{
			ID:        docID,
			Source:    "chat",
			Timestamp: now,
			Metadata:  map[string]string{"type": "chat_message"},
		},
		Chunks: []ingestChunk{
			{DocID: docID, Content: "User: how do I set up the server?", TokenCount: 30, Vector: makeVec(1.0)},
			{DocID: docID, Content: "Assistant: run go run cmd/server/main.go", TokenCount: 40, Vector: makeVec(0.95)},
			{DocID: docID, Content: "User: ok now I want memory retrieval", TokenCount: 35, Vector: makeVec(0.9)},
		},
	}

	raw, code, err := postJSON("/ingest", req)
	if err != nil {
		panic(err)
	}
	fmt.Println("ingest", code, raw)

	rreq := retrieveRequest{
		Namespace: namespace,
		Query:     makeVec(1.0),
		MaxTokens: 120,
	}
	raw, code, err = postJSON("/retrieve", rreq)
	if err != nil {
		panic(err)
	}
	fmt.Println("retrieve", code, raw)
}

func postJSON(path string, payload any) (string, int, error) {
	b, err := json.Marshal(payload)
	if err != nil {
		return "", 0, err
	}
	resp, err := http.Post(baseURL+path, "application/json", bytes.NewBuffer(b))
	if err != nil {
		return "", 0, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return string(body), resp.StatusCode, nil
}
