
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

type ingestMessageRequest struct {
	Namespace      string `json:"namespace"`
	ConversationID string `json:"conversation_id"`
	MessageID      string `json:"message_id,omitempty"`
	Role           string `json:"role"`
	Content        string `json:"content"`
	Vector         vector `json:"vector"`
	TokenCount     int    `json:"token_count"`
	TimestampUTC   string `json:"timestamp_utc,omitempty"`
	Source         string `json:"source,omitempty"`
}

type retrieveRequest struct {
	Namespace string `json:"namespace,omitempty"`
	Query     vector `json:"query"`
	MaxTokens int    `json:"max_tokens"`
}

func main() {
	// Demo values; in the IDE these would be stable per project + per chat thread.
	namespace := "demo-project-123"
	conversationID := "conv-default"

	// The engine is configured for 1536-d vectors by default.
	dim := 1536
	makeVec := func(seed float32) vector {
		v := make(vector, dim)
		// Put a few non-zero values to avoid being all zeros.
		v[0] = seed
		v[1] = seed * 0.5
		v[2] = seed * 0.25
		return v
	}

	now := time.Now().UTC()

	// Ingest 3 messages
	msgs := []ingestMessageRequest{
		{
			Namespace:      namespace,
			ConversationID: conversationID,
			Role:           "user",
			Content:        "How do I set up the server?",
			Vector:         makeVec(1.0),
			TokenCount:     10,
			TimestampUTC:   now.Format(time.RFC3339),
			Source:         "chat",
		},
		{
			Namespace:      namespace,
			ConversationID: conversationID,
			Role:           "assistant",
			Content:        "Run: go run cmd/server/main.go",
			Vector:         makeVec(0.95),
			TokenCount:     12,
			TimestampUTC:   now.Add(2 * time.Second).Format(time.RFC3339),
			Source:         "chat",
		},
		{
			Namespace:      namespace,
			ConversationID: conversationID,
			Role:           "user",
			Content:        "Ok, now I want memory retrieval.",
			Vector:         makeVec(0.9),
			TokenCount:     8,
			TimestampUTC:   now.Add(4 * time.Second).Format(time.RFC3339),
			Source:         "chat",
		},
	}

	for i, m := range msgs {
		raw, code, err := postJSON("/ingest_message", m)
		if err != nil {
			panic(err)
		}
		fmt.Printf("ingest_message[%d] %d %s\n", i, code, raw)
	}

	// Retrieve using a similar query vector
	rreq := retrieveRequest{
		Namespace: namespace,
		Query:     makeVec(1.0),
		MaxTokens: 200,
	}
	raw, code, err := postJSON("/retrieve", rreq)
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
