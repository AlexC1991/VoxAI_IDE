
package index

import (
	"math"
	"math/rand"
	"sort"
	"sync"
	"vox-vector-engine/internal/storage"
	"vox-vector-engine/internal/types"
)

const (
	MaxLevel       = 16
	M              = 16 // Max connections per layer
	M0             = 32 // Max connections for layer 0
	EfConstruction = 40
	EfSearch       = 50
)

type Node struct {
	ID        uint64
	Level     int
	Neighbors [][]uint64 // [level][neighbors]
}

type HnswIndex struct {
	nodes           map[uint64]*Node
	vecs            storage.VectorStore // Source of truth for vectors
	entryPointID    uint64
	maxLevel        int
	currentMaxLevel int
	mu              sync.RWMutex
}

func NewHnswIndex(vecs storage.VectorStore) *HnswIndex {
	return &HnswIndex{
		nodes:           make(map[uint64]*Node),
		vecs:            vecs,
		maxLevel:        MaxLevel,
		currentMaxLevel: -1,
	}
}

// Reset clears the in-memory graph. It does NOT modify the underlying vector store.
// This is intended for dev/test; production should isolate with namespaces.
func (idx *HnswIndex) Reset() {
	idx.mu.Lock()
	defer idx.mu.Unlock()

	idx.nodes = make(map[uint64]*Node)
	idx.entryPointID = 0
	idx.currentMaxLevel = -1
}

func (idx *HnswIndex) Add(id uint64, vector types.Vector) {
	idx.mu.Lock()
	defer idx.mu.Unlock()

	level := idx.randomLevel()
	node := &Node{
		ID:        id,
		Level:     level,
		Neighbors: make([][]uint64, level+1),
	}
	idx.nodes[id] = node

	if idx.currentMaxLevel == -1 {
		idx.entryPointID = id
		idx.currentMaxLevel = level
		return
	}

	currEntryPoint := idx.entryPointID

	// 1. Find the nearest entry point at node's level by traversing top levels
	for l := idx.currentMaxLevel; l > level; l-- {
		epVec, _ := idx.vecs.Get(currEntryPoint)
		currEntryPoint, _ = idx.searchLayer(vector, currEntryPoint, epVec, 1, l)
	}

	// 2. Insert into layers from top-down
	for l := min(level, idx.currentMaxLevel); l >= 0; l-- {
		// Find neighbors at this level
		nearestIDs, _ := idx.searchLayerK(vector, currEntryPoint, EfConstruction, l)

		// Select M neighbors (simplified: just take top M)
		m := M
		if l == 0 {
			m = M0
		}
		if len(nearestIDs) > m {
			nearestIDs = nearestIDs[:m]
		}

		// Connect bidirectionally
		node.Neighbors[l] = nearestIDs
		for _, neighborID := range nearestIDs {
			neighbor := idx.nodes[neighborID]
			neighbor.Neighbors[l] = append(neighbor.Neighbors[l], id)
		}

		// Update entry point for next level
		if len(nearestIDs) > 0 {
			currEntryPoint = nearestIDs[0]
		}
	}

	if level > idx.currentMaxLevel {
		idx.entryPointID = id
		idx.currentMaxLevel = level
	}
}

func (idx *HnswIndex) Search(query types.Vector, k int) ([]uint64, []float32) {
	idx.mu.RLock()
	defer idx.mu.RUnlock()

	if idx.currentMaxLevel == -1 {
		return nil, nil
	}

	currEP := idx.entryPointID
	for l := idx.currentMaxLevel; l > 0; l-- {
		epVec, _ := idx.vecs.Get(currEP)
		currEP, _ = idx.searchLayer(query, currEP, epVec, 1, l)
	}

	ids, dists := idx.searchLayerK(query, currEP, EfSearch, 0)

	count := k
	if len(ids) < k {
		count = len(ids)
	}

	return ids[:count], dists[:count]
}

// searchLayer finds the single nearest node at a level (greedy search)
func (idx *HnswIndex) searchLayer(query types.Vector, entryPoint uint64, epVec types.Vector, ef int, level int) (uint64, float32) {
	curr := entryPoint
	currDist := euclideanDistance(query, epVec)

	changed := true
	for changed {
		changed = false
		node := idx.nodes[curr]
		for _, neighborID := range node.Neighbors[level] {
			nVec, _ := idx.vecs.Get(neighborID)
			d := euclideanDistance(query, nVec)
			if d < currDist {
				currDist = d
				curr = neighborID
				changed = true
			}
		}
	}
	return curr, currDist
}

type neighborResult struct {
	id   uint64
	dist float32
}

// searchLayerK finds K nearest neighbors at a level
func (idx *HnswIndex) searchLayerK(query types.Vector, entryPoint uint64, k int, level int) ([]uint64, []float32) {
	epVec, _ := idx.vecs.Get(entryPoint)
	visited := map[uint64]bool{entryPoint: true}
	candidates := []neighborResult{{entryPoint, euclideanDistance(query, epVec)}}
	results := []neighborResult{candidates[0]}

	for len(candidates) > 0 {
		c := candidates[0]
		candidates = candidates[1:]

		if len(results) >= k && c.dist > results[len(results)-1].dist {
			continue
		}

		node := idx.nodes[c.id]
		for _, neighborID := range node.Neighbors[level] {
			if !visited[neighborID] {
				visited[neighborID] = true
				nVec, _ := idx.vecs.Get(neighborID)
				d := euclideanDistance(query, nVec)

				if len(results) < k || d < results[len(results)-1].dist {
					res := neighborResult{neighborID, d}
					candidates = append(candidates, res)
					results = append(results, res)

					sort.Slice(results, func(i, j int) bool { return results[i].dist < results[j].dist })
					if len(results) > k {
						results = results[:k]
					}
					sort.Slice(candidates, func(i, j int) bool { return candidates[i].dist < candidates[j].dist })
				}
			}
		}
	}

	ids := make([]uint64, len(results))
	dists := make([]float32, len(results))
	for i := range results {
		ids[i] = results[i].id
		dists[i] = results[i].dist
	}
	return ids, dists
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func (idx *HnswIndex) randomLevel() int {
	lvl := 0
	for rand.Float64() < 0.5 && lvl < idx.maxLevel {
		lvl++
	}
	return lvl
}

func euclideanDistance(a, b types.Vector) float32 {
	var sum float32
	for i := range a {
		diff := a[i] - b[i]
		sum += diff * diff
	}
	return float32(math.Sqrt(float64(sum)))
}
