package storage

import (
	"encoding/json"
	"fmt"
	"time"

	"vox-vector-engine/internal/types"

	"go.etcd.io/bbolt"
)

var (
	bucketDocs   = []byte("documents")
	bucketChunks = []byte("chunks")
)

type BoltMetadataStore struct {
	db *bbolt.DB
}

func NewBoltMetadataStore(path string) (*BoltMetadataStore, error) {
	db, err := bbolt.Open(path, 0600, &bbolt.Options{Timeout: 5 * time.Second})
	if err != nil {
		return nil, err
	}

	err = db.Update(func(tx *bbolt.Tx) error {
		if _, err := tx.CreateBucketIfNotExists(bucketDocs); err != nil {
			return err
		}
		if _, err := tx.CreateBucketIfNotExists(bucketChunks); err != nil {
			return err
		}
		return nil
	})
	if err != nil {
		db.Close()
		return nil, err
	}

	return &BoltMetadataStore{db: db}, nil
}

func (s *BoltMetadataStore) SaveDocument(doc types.Document) error {
	return s.db.Update(func(tx *bbolt.Tx) error {
		b := tx.Bucket(bucketDocs)
		data, err := json.Marshal(doc)
		if err != nil {
			return err
		}
		return b.Put([]byte(doc.ID), data)
	})
}

func (s *BoltMetadataStore) GetDocument(id string) (*types.Document, error) {
	var doc types.Document
	err := s.db.View(func(tx *bbolt.Tx) error {
		b := tx.Bucket(bucketDocs)
		data := b.Get([]byte(id))
		if data == nil {
			return fmt.Errorf("document not found: %s", id)
		}
		return json.Unmarshal(data, &doc)
	})
	if err != nil {
		return nil, err
	}
	return &doc, nil
}

func (s *BoltMetadataStore) SaveChunk(chunk types.Chunk) error {
	return s.db.Update(func(tx *bbolt.Tx) error {
		b := tx.Bucket(bucketChunks)
		data, err := json.Marshal(chunk)
		if err != nil {
			return err
		}
		// Use uint64 ID as key
		return b.Put([]byte(fmt.Sprintf("%d", chunk.ID)), data)
	})
}

func (s *BoltMetadataStore) GetChunk(id uint64) (*types.Chunk, error) {
	var chunk types.Chunk
	err := s.db.View(func(tx *bbolt.Tx) error {
		b := tx.Bucket(bucketChunks)
		data := b.Get([]byte(fmt.Sprintf("%d", id)))
		if data == nil {
			return fmt.Errorf("chunk not found: %d", id)
		}
		return json.Unmarshal(data, &chunk)
	})
	if err != nil {
		return nil, err
	}
	return &chunk, nil
}

func (s *BoltMetadataStore) Close() error {
	return s.db.Close()
}
