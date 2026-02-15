package engine

import (
	"sort"
	"time"

	"vox-vector-engine/internal/index"
	"vox-vector-engine/internal/storage"
	"vox-vector-engine/internal/types"
)

type RetrievalConfig struct {
	MaxTokens        int
	SimilarityWeight float32
	RecencyWeight    float32
	TopKCandidates   int // How many to fetch from ANN before re-ranking

	// Namespace: optional logical partition (e.g. project/workspace/repo/chat_id).
	// If set, only chunks whose Document.Metadata["namespace"] matches will be returned.
	Namespace string
}

type RetrievalResult struct {
	Chunks      []ScoredChunk `json:"chunks"`
	TotalTokens int           `json:"total_tokens"`
	Truncated   bool          `json:"truncated"`
}

type Engine struct {
	index    *index.HnswIndex
	vectors  storage.VectorStore
	metadata *storage.BoltMetadataStore
}

func NewEngine(idx *index.HnswIndex, output storage.VectorStore, meta *storage.BoltMetadataStore) *Engine {
	return &Engine{
		index:    idx,
		vectors:  output,
		metadata: meta,
	}
}

type ScoredChunk struct {
	Chunk      types.Chunk `json:"chunk"`
	Similarity float32     `json:"similarity"`
	Recency    float32     `json:"recency"`
}

func (e *Engine) Retrieve(query types.Vector, config RetrievalConfig) (*RetrievalResult, error) {
	ids, dists := e.index.Search(query, config.TopKCandidates)

	candidates := make([]ScoredChunk, 0, len(ids))

	for i, id := range ids {
		chunk, err := e.metadata.GetChunk(id)
		if err != nil {
			continue
		}

		doc, docErr := e.metadata.GetDocument(chunk.DocID)
		if config.Namespace != "" {
			if docErr != nil {
				continue
			}
			if doc.Metadata == nil {
				continue
			}
			ns, ok := doc.Metadata["namespace"].(string)
			if !ok || ns != config.Namespace {
				continue
			}
		}

		simScore := float32(1.0 / (1.0 + dists[i]))
		recencyScore := float32(0.5) // default
		if docErr == nil {
			recencyScore = calculateRecency(doc.Timestamp)
		}

		finalScore := simScore*config.SimilarityWeight + recencyScore*config.RecencyWeight

		candidates = append(candidates, ScoredChunk{
			Chunk:      *chunk,
			Similarity: finalScore,
			Recency:    recencyScore,
		})
	}

	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].Similarity > candidates[j].Similarity
	})

	result := &RetrievalResult{
		Chunks: []ScoredChunk{},
	}

	for _, cand := range candidates {
		if result.TotalTokens+cand.Chunk.TokenCount > config.MaxTokens {
			result.Truncated = true
			continue
		}
		result.Chunks = append(result.Chunks, cand)
		result.TotalTokens += cand.Chunk.TokenCount
	}

	return result, nil
}

func calculateRecency(t time.Time) float32 {
	hours := time.Since(t).Hours()
	return float32(1.0 / (1.0 + hours/24.0))
}
