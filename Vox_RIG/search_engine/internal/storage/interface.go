package storage

import "vox-vector-engine/internal/types"

// VectorStore defines the interface for storing and retrieving raw vectors.
type VectorStore interface {
	// Append adds a vector to the store and returns its index.
	Append(vector types.Vector) (uint64, error)

	// Get retrieves a vector by its index.
	Get(index uint64) (types.Vector, error)

	// Count returns the number of vectors in the store.
	Count() uint64

	// Close flushes and closes the store.
	Close() error
}
