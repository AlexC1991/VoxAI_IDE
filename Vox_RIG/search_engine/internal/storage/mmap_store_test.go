
package storage

import (
	"os"
	"testing"

	"vox-vector-engine/internal/types"
)

func TestMmapVectorStore(t *testing.T) {
	tmpFile := "test_vectors.bin"
	defer os.Remove(tmpFile)

	// 1. Create and Write
	store, err := NewMmapVectorStore(tmpFile, 2) // 2D vectors
	if err != nil {
		t.Fatalf("Failed to create store: %v", err)
	}

	vec1 := types.Vector{1.0, 2.0}
	vec2 := types.Vector{3.0, 4.0}

	id1, err := store.Append(vec1)
	if err != nil {
		t.Fatalf("Failed to append vec1: %v", err)
	}
	if id1 != 0 {
		t.Errorf("Expected id 0, got %d", id1)
	}

	id2, err := store.Append(vec2)
	if err != nil {
		t.Fatalf("Failed to append vec2: %v", err)
	}
	if id2 != 1 {
		t.Errorf("Expected id 1, got %d", id2)
	}

	if count := store.Count(); count != 2 {
		t.Errorf("Expected count 2, got %d", count)
	}

	// 2. Read back
	v1, err := store.Get(0)
	if err != nil {
		t.Fatalf("Failed to get vec1: %v", err)
	}
	if v1[0] != 1.0 || v1[1] != 2.0 {
		t.Errorf("Vec1 mismatch: %v", v1)
	}

	v2, err := store.Get(1)
	if err != nil {
		t.Fatalf("Failed to get vec2: %v", err)
	}
	if v2[0] != 3.0 || v2[1] != 4.0 {
		t.Errorf("Vec2 mismatch: %v", v2)
	}

	// 3. Close and Reopen (Persistence)
	_ = store.Close()

	store2, err := NewMmapVectorStore(tmpFile, 2)
	if err != nil {
		t.Fatalf("Failed to reopen store: %v", err)
	}
	defer store2.Close()

	if count := store2.Count(); count != 2 {
		t.Errorf("Reopened count mismatch. Expected 2, got %d", count)
	}

	v2Reopen, err := store2.Get(1)
	if err != nil {
		t.Fatalf("Failed to get vec2 after reopen: %v", err)
	}
	if v2Reopen[0] != 3.0 || v2Reopen[1] != 4.0 {
		t.Errorf("Vec2 mismatch after reopen: %v", v2Reopen)
	}
}

func TestMmapVectorStore_DimMismatch(t *testing.T) {
	tmpFile := "test_vectors_dim_mismatch.bin"
	defer os.Remove(tmpFile)

	store, err := NewMmapVectorStore(tmpFile, 2)
	if err != nil {
		t.Fatalf("Failed to create store: %v", err)
	}
	if _, err := store.Append(types.Vector{1, 2}); err != nil {
		t.Fatalf("Failed to append: %v", err)
	}
	_ = store.Close()

	_, err = NewMmapVectorStore(tmpFile, 3)
	if err == nil {
		t.Fatalf("Expected error on dim mismatch, got nil")
	}
}
