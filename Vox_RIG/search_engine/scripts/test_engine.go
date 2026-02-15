
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"vox-vector-engine/internal/types"
)

const baseURL = "http://localhost:8080"

type ingestChunk struct {
	DocID      string       `json:"doc_id"`
	Vector     types.Vector `json:"vector"`
	Content    string       `json:"content"`
	StartLine  int          `json:"start_line"`
	EndLine    int          `json:"end_line"`
	TokenCount int          `json:"token_count"`
}

type ingestRequest struct {
	Document types.Document `json:"document"`
	Chunks   []ingestChunk  `json:"chunks"`
}

type ingestResponse struct {
	Status      string   `json:"status"`
	DocID       string   `json:"doc_id"`
	ChunkIDs    []uint64 `json:"chunk_ids"`
	VectorCount int      `json:"vector_count"`
}

type retrieveRequest struct {
	Query     types.Vector `json:"query"`
	MaxTokens int          `json:"max_tokens"`
}

type retrieveChunk struct {
	ID         uint64 `json:"id"`
	DocID      string `json:"doc_id"`
	Content    string `json:"content"`
	StartLine  int    `json:"start_line"`
	EndLine    int    `json:"end_line"`
	TokenCount int    `json:"token_count"`
}

type retrieveResponse struct {
	Chunks      []retrieveChunk `json:"Chunks"`
	TotalTokens int             `json:"TotalTokens"`
	Truncated   bool            `json:"Truncated"`
}

// Cache formats: compact + stable keys for easy AI parsing.
type cacheFile struct {
	Schema   int       `json:"schema"`
	TimeUTC  string    `json:"time_utc"`
	Server   string    `json:"server"`
	RunID    string    `json:"run_id"`
	DocOldID string    `json:"doc_old_id"`
	DocNewID string    `json:"doc_new_id"`
	Pass     bool      `json:"pass"`
	Failures []string  `json:"failures,omitempty"`
	Checks   []check   `json:"checks"`
	Raw      rawBlocks `json:"raw,omitempty"`
}

type check struct {
	Name string `json:"name"`           // stable id (no spaces)
	OK   bool   `json:"ok"`             // pass/fail
	Info string `json:"info,omitempty"` // short note (kept small)
}

type rawBlocks struct {
	IngestOld string `json:"ingest_old,omitempty"`
	IngestNew string `json:"ingest_new,omitempty"`
	R150      string `json:"retrieve_150,omitempty"`
	R500      string `json:"retrieve_500,omitempty"`
}

func main() {
	human := os.Getenv("HUMAN") == "1" || os.Getenv("HUMAN") == "true"
	dumpRaw := os.Getenv("RAW") == "1" || os.Getenv("RAW") == "true"

	runID := time.Now().UTC().Format("20060102T150405Z")

	docOldID := "doc-old-" + runID
	docNewID := "doc-new-" + runID

	cache := cacheFile{
		Schema:   1,
		TimeUTC:  time.Now().UTC().Format(time.RFC3339),
		Server:   baseURL,
		RunID:    runID,
		DocOldID: docOldID,
		DocNewID: docNewID,
		Pass:     true,
		Checks:   make([]check, 0, 10),
	}
	fail := func(name, msg string) {
		cache.Pass = false
		cache.Failures = append(cache.Failures, fmt.Sprintf("%s: %s", name, msg))
		cache.Checks = append(cache.Checks, check{Name: name, OK: false, Info: msg})
	}

	ok := func(name, msg string) {
		cache.Checks = append(cache.Checks, check{Name: name, OK: true, Info: msg})
	}

	if human {
		fmt.Println("Vector Engine Test (token efficient + cache)")
		fmt.Println("-------------------------------------------")
		fmt.Println("run_id:", runID)
		fmt.Println("doc_old:", docOldID)
		fmt.Println("doc_new:", docNewID)
	}

	// Wait for server
	if err := waitForServer(baseURL, 5*time.Second); err != nil {
		fail("server_reachable", err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	ok("server_reachable", "reachable")

	// Prepare vectors
	dim := 1536
	vec1 := make(types.Vector, dim)
	vec1[0] = 1.0
	vec2 := make(types.Vector, dim)
	vec2[0] = 0.9

	docOld := types.Document{
		ID:        docOldID,
		Source:    "old_file.go",
		Timestamp: time.Now().Add(-24 * time.Hour),
		Metadata:  types.Metadata{"importance": "high", "run_id": runID},
	}
	docNew := types.Document{
		ID:        docNewID,
		Source:    "new_file.go",
		Timestamp: time.Now(),
		Metadata:  types.Metadata{"importance": "medium", "run_id": runID},
	}

	// 1) Ingest old
	if human {
		fmt.Println("1) ingest old")
	}
	req1 := ingestRequest{
		Document: docOld,
		Chunks: []ingestChunk{
			{DocID: docOldID, Content: "This is old content that is very long...", TokenCount: 200, Vector: vec1},
		},
	}
	raw1, status, err := sendRequest("/ingest", req1)
	if dumpRaw {
		cache.Raw.IngestOld = raw1
	}
	if err != nil {
		fail("ingest_old", "request_error: "+err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if status < 200 || status >= 300 {
		fail("ingest_old", fmt.Sprintf("http_%d", status))
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	var ing1 ingestResponse
	if err := json.Unmarshal([]byte(raw1), &ing1); err != nil {
		fail("ingest_old", "json_parse_error: "+err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if ing1.Status != "ingested" || ing1.DocID != docOldID || len(ing1.ChunkIDs) == 0 {
		fail("ingest_old", "unexpected_payload")
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	ok("ingest_old", fmt.Sprintf("chunk_id=%d vec_count=%d", ing1.ChunkIDs[0], ing1.VectorCount))

	// 2) Ingest new
	if human {
		fmt.Println("2) ingest new")
	}
	req2 := ingestRequest{
		Document: docNew,
		Chunks: []ingestChunk{
			{DocID: docNewID, Content: "This is new content, slightly less similar but more recent.", TokenCount: 100, Vector: vec2},
		},
	}
	raw2, status, err := sendRequest("/ingest", req2)
	if dumpRaw {
		cache.Raw.IngestNew = raw2
	}
	if err != nil {
		fail("ingest_new", "request_error: "+err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if status < 200 || status >= 300 {
		fail("ingest_new", fmt.Sprintf("http_%d", status))
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	var ing2 ingestResponse
	if err := json.Unmarshal([]byte(raw2), &ing2); err != nil {
		fail("ingest_new", "json_parse_error: "+err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if ing2.Status != "ingested" || ing2.DocID != docNewID || len(ing2.ChunkIDs) == 0 {
		fail("ingest_new", "unexpected_payload")
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	ok("ingest_new", fmt.Sprintf("chunk_id=%d vec_count=%d", ing2.ChunkIDs[0], ing2.VectorCount))

	// 3) Retrieve 150: must include doc-new for this run; must not exceed budget
	if human {
		fmt.Println("3) retrieve 150")
	}
	query := make(types.Vector, dim)
	query[0] = 1.0
	rawR1, status, err := sendRequest("/retrieve", retrieveRequest{Query: query, MaxTokens: 150})
	if dumpRaw {
		cache.Raw.R150 = rawR1
	}
	if err != nil {
		fail("retrieve_150", "request_error: "+err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if status < 200 || status >= 300 {
		fail("retrieve_150", fmt.Sprintf("http_%d", status))
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	var r1 retrieveResponse
	if err := json.Unmarshal([]byte(rawR1), &r1); err != nil {
		fail("retrieve_150", "json_parse_error: "+err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if r1.TotalTokens > 150 {
		fail("retrieve_150", fmt.Sprintf("budget_exceeded tokens=%d", r1.TotalTokens))
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if !containsDocID(r1, docNewID) {
		fail("retrieve_150", "missing_doc_new")
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if containsDocID(r1, docOldID) {
		fail("retrieve_150", "unexpected_doc_old_included")
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	ok("retrieve_150", fmt.Sprintf("chunks=%d tokens=%d trunc=%v", len(r1.Chunks), r1.TotalTokens, r1.Truncated))

	// 4) Retrieve 500: must include both doc-new and doc-old for this run; budget respected.
	// Don’t require exact chunk count because engine may contain previous test data.
	if human {
		fmt.Println("4) retrieve 500")
	}
	rawR2, status, err := sendRequest("/retrieve", retrieveRequest{Query: query, MaxTokens: 500})
	if dumpRaw {
		cache.Raw.R500 = rawR2
	}
	if err != nil {
		fail("retrieve_500", "request_error: "+err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if status < 200 || status >= 300 {
		fail("retrieve_500", fmt.Sprintf("http_%d", status))
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	var r2 retrieveResponse
	if err := json.Unmarshal([]byte(rawR2), &r2); err != nil {
		fail("retrieve_500", "json_parse_error: "+err.Error())
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if r2.TotalTokens > 500 {
		fail("retrieve_500", fmt.Sprintf("budget_exceeded tokens=%d", r2.TotalTokens))
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if !containsDocID(r2, docNewID) || !containsDocID(r2, docOldID) {
		fail("retrieve_500", fmt.Sprintf("missing_expected_docs have=%s", docsPresent(r2, docNewID, docOldID)))
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}

	// Optional: ensure doc-new appears before doc-old among the *first occurrences* in result.
	posNew := firstIndexOfDocID(r2, docNewID)
	posOld := firstIndexOfDocID(r2, docOldID)
	if posNew == -1 || posOld == -1 {
		fail("retrieve_500", "unexpected_indexing_error")
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}
	if posNew > posOld {
		fail("retrieve_500", fmt.Sprintf("unexpected_order new_at=%d old_at=%d", posNew, posOld))
		writeCache(cache, dumpRaw)
		printSummary(cache, human)
		return
	}

	ok("retrieve_500", fmt.Sprintf("chunks=%d tokens=%d trunc=%v", len(r2.Chunks), r2.TotalTokens, r2.Truncated))

	writeCache(cache, dumpRaw)
	printSummary(cache, human)
}

func printSummary(cache cacheFile, human bool) {
	cachePath := cacheOutputPath()

	if human {
		if cache.Pass {
			fmt.Println("RESULT: PASS")
		} else {
			fmt.Println("RESULT: FAIL")
			for _, f := range cache.Failures {
				fmt.Println(" -", f)
			}
		}
		fmt.Println("Cache:", cachePath)
		return
	}

	// Token-efficient, single-line verdict for AI logs.
	if cache.Pass {
		fmt.Printf("PASS cache=%s run_id=%s\n", cachePath, cache.RunID)
	} else {
		if len(cache.Failures) > 0 {
			fmt.Printf("FAIL %s cache=%s run_id=%s\n", firstFailureCompact(cache.Failures[0]), cachePath, cache.RunID)
		} else {
			fmt.Printf("FAIL cache=%s run_id=%s\n", cachePath, cache.RunID)
		}
	}
}

func firstFailureCompact(f string) string {
	// keep single-line tight
	f = strings.ReplaceAll(f, "\n", " ")
	f = strings.TrimSpace(f)
	if len(f) > 140 {
		return f[:140]
	}
	return f
}

func cacheOutputPath() string {
	return filepath.FromSlash("scripts/.cache/test_engine_cache.json")
}

func writeCache(cache cacheFile, includeRaw bool) {
	if !includeRaw {
		cache.Raw = rawBlocks{}
	}
	path := cacheOutputPath()
	_ = os.MkdirAll(filepath.Dir(path), 0o755)
	b, err := json.Marshal(cache)
	if err != nil {
		return
	}
	_ = os.WriteFile(path, b, 0o644)
}

func containsDocID(r retrieveResponse, docID string) bool {
	for _, c := range r.Chunks {
		if c.DocID == docID {
			return true
		}
	}
	return false
}

func firstIndexOfDocID(r retrieveResponse, docID string) int {
	for i, c := range r.Chunks {
		if c.DocID == docID {
			return i
		}
	}
	return -1
}

func docsPresent(r retrieveResponse, newID, oldID string) string {
	hasNew := containsDocID(r, newID)
	hasOld := containsDocID(r, oldID)
	return fmt.Sprintf("new=%v old=%v", hasNew, hasOld)
}

func sendRequest(endpoint string, data interface{}) (string, int, error) {
	b, err := json.Marshal(data)
	if err != nil {
		return "", 0, err
	}

	resp, err := http.Post(baseURL+endpoint, "application/json", bytes.NewBuffer(b))
	if err != nil {
		return "", 0, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	return string(body), resp.StatusCode, nil
}

func waitForServer(url string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	client := &http.Client{Timeout: 1 * time.Second}

	for time.Now().Before(deadline) {
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		resp, err := client.Do(req)
		if err == nil {
			_ = resp.Body.Close()
			return nil
		}
		time.Sleep(200 * time.Millisecond)
	}
	return fmt.Errorf("timed out after %s", timeout)
}
