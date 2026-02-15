//go:build !windows

package storage

import (
	"fmt"
	"syscall"
)

func (s *MmapVectorStore) mmap(size int64) error {
	data, err := syscall.Mmap(int(s.file.Fd()), 0, int(size), syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_SHARED)
	if err != nil {
		return fmt.Errorf("mmap failed: %w", err)
	}
	s.mapped = data
	return nil
}

func (s *MmapVectorStore) munmap() error {
	if s.mapped != nil {
		err := syscall.Munmap(s.mapped)
		s.mapped = nil
		return err
	}
	return nil
}
