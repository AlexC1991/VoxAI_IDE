package types

import "time"

// Vector represents a high-dimensional float32 vector.
type Vector []float32

// Metadata stores associated key-value pairs for a document or chunk.
type Metadata map[string]interface{}

// Document represents a source file or logical unit of content.
type Document struct {
	ID        string    `json:"id"`
	Source    string    `json:"source"`    // e.g., file path
	Timestamp time.Time `json:"timestamp"` // Modification time
	Metadata  Metadata  `json:"metadata"`
}

// Chunk represents a segment of a document with its vector embedding.
type Chunk struct {
	ID         uint64 `json:"id"` // Internal sequential ID
	DocID      string `json:"doc_id"`
	Vector     Vector `json:"-"`       // Exclude from JSON to avoid BoltDB bloat
	Content    string `json:"content"` // The actual text content
	StartLine  int    `json:"start_line"`
	EndLine    int    `json:"end_line"`
	TokenCount int    `json:"token_count"`
}
