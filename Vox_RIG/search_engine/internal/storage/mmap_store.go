
package storage

import (
	"encoding/binary"
	"errors"
	"fmt"
	"os"
	"sync"
	"unsafe"

	"vox-vector-engine/internal/types"
)

const (
	vectorSize = 4 // float32 is 4 bytes

	// File header (v1):
	//   0..7   magic "VOXVEC01"
	//   8..15  dim (uint64)
	//   16..23 count (uint64)
	HeaderSize = 24
)

var fileMagic = [8]byte{'V', 'O', 'X', 'V', 'E', 'C', '0', '1'}

// MmapVectorStore implements VectorStore using memory-mapped files.
// Note: This is a Windows-specific implementation using syscall.
type MmapVectorStore struct {
	filename   string
	file       *os.File
	mu         sync.RWMutex
	mapped     []byte
	dim        int
	count      uint64
	capacity   uint64
	mapHandle  uintptr // syscall.Handle on Windows
	viewHandle uintptr // MapViewOfFile address
}

func NewMmapVectorStore(filename string, dim int) (*MmapVectorStore, error) {
	if dim <= 0 {
		return nil, fmt.Errorf("invalid dim: %d", dim)
	}

	f, err := os.OpenFile(filename, os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		return nil, fmt.Errorf("failed to open file: %w", err)
	}

	info, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return nil, err
	}

	store := &MmapVectorStore{
		filename: filename,
		file:     f,
		dim:      dim,
	}

	size := info.Size()

	// Initialize if empty
	if size == 0 {
		if err := store.initNew(); err != nil {
			_ = f.Close()
			return nil, err
		}
	}

	if err := store.remap(); err != nil {
		_ = f.Close()
		return nil, err
	}

	// Read + validate header (and set count/dim from disk)
	onDiskDim, onDiskCount, err := store.readAndValidateHeader()
	if err != nil {
		_ = store.Close()
		return nil, err
	}

	// Enforce "proper" configuration: dim is stored in the file and must match CLI dim.
	if int(onDiskDim) != store.dim {
		_ = store.Close()
		return nil, fmt.Errorf("vector dimension mismatch: file dim=%d, requested dim=%d (delete %s to reset)", onDiskDim, store.dim, filename)
	}
	store.count = onDiskCount

	return store, nil
}

func (s *MmapVectorStore) initNew() error {
	// initial capacity: header + space for 1024 vectors
	initialSize := int64(HeaderSize + 1024*s.dim*vectorSize)
	if err := s.resize(initialSize); err != nil {
		return err
	}
	if err := s.remap(); err != nil {
		return err
	}
	s.writeHeader(uint64(s.dim), 0)
	s.count = 0
	return nil
}

func (s *MmapVectorStore) readAndValidateHeader() (dim uint64, count uint64, err error) {
	if len(s.mapped) < HeaderSize {
		return 0, 0, fmt.Errorf("vectors file too small for header: %d < %d", len(s.mapped), HeaderSize)
	}

	var mg [8]byte
	copy(mg[:], s.mapped[:8])
	if mg != fileMagic {
		return 0, 0, errors.New("invalid vectors file header (magic mismatch): delete vectors.bin to reset")
	}

	dim = binary.LittleEndian.Uint64(s.mapped[8:16])
	count = binary.LittleEndian.Uint64(s.mapped[16:24])
	if dim == 0 {
		return 0, 0, errors.New("invalid vectors file header (dim=0): delete vectors.bin to reset")
	}
	return dim, count, nil
}

func (s *MmapVectorStore) writeHeader(dim uint64, count uint64) {
	copy(s.mapped[:8], fileMagic[:])
	binary.LittleEndian.PutUint64(s.mapped[8:16], dim)
	binary.LittleEndian.PutUint64(s.mapped[16:24], count)
}

func (s *MmapVectorStore) resize(newSize int64) error {
	if err := s.munmap(); err != nil {
		return err
	}
	if err := s.file.Truncate(newSize); err != nil {
		return err
	}
	return nil
}

func (s *MmapVectorStore) remap() error {
	// Always unmap any existing view before mapping a new one.
	// Append() may call remap() after resize(), but NewMmapVectorStore() calls remap()
	// without a prior munmap(). Re-mapping without unmapping leaks handles and can
	// cause MapViewOfFile/CreateFileMapping failures on Windows.
	if err := s.munmap(); err != nil {
		return err
	}

	fi, err := s.file.Stat()
	if err != nil {
		return err
	}
	size := fi.Size()
	if size == 0 {
		return nil
	}

	return s.mmap(size)
}

func (s *MmapVectorStore) Append(vector types.Vector) (uint64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if len(vector) != s.dim {
		return 0, fmt.Errorf("vector dimension mismatch: expected %d, got %d", s.dim, len(vector))
	}

	// Compute required bytes for header + N vectors
	requiredSize := int64(HeaderSize + (int(s.count)+1)*s.dim*vectorSize)
	if requiredSize > int64(len(s.mapped)) {
		// Grow by 50% or at least required size
		newSize := int64(len(s.mapped)) + int64(len(s.mapped))/2
		if newSize < requiredSize {
			newSize = requiredSize
		}

		if err := s.resize(newSize); err != nil {
			return 0, fmt.Errorf("resize failed: %w", err)
		}
		if err := s.remap(); err != nil {
			return 0, fmt.Errorf("remap failed: %w", err)
		}
		// After remap, header must still exist; ensure it's correct
		s.writeHeader(uint64(s.dim), s.count)
	}

	offset := HeaderSize + int(s.count)*s.dim*vectorSize

	// Write vector
	for i, v := range vector {
		bits := *(*uint32)(unsafe.Pointer(&v))
		binary.LittleEndian.PutUint32(s.mapped[offset+i*4:], bits)
	}

	s.count++
	// Update count header (and keep magic/dim stable)
	s.writeHeader(uint64(s.dim), s.count)

	return s.count - 1, nil
}

func (s *MmapVectorStore) Get(index uint64) (types.Vector, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	if index >= s.count {
		return nil, fmt.Errorf("index out of bounds: %d >= %d", index, s.count)
	}

	offset := HeaderSize + int(index)*s.dim*vectorSize
	vec := make(types.Vector, s.dim)

	for i := 0; i < s.dim; i++ {
		bits := binary.LittleEndian.Uint32(s.mapped[offset+i*4:])
		vec[i] = *(*float32)(unsafe.Pointer(&bits))
	}

	return vec, nil
}

func (s *MmapVectorStore) Count() uint64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.count
}

func (s *MmapVectorStore) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	_ = s.munmap()
	return s.file.Close()
}
