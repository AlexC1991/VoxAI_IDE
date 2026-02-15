
//go:build windows

package storage

import (
	"fmt"
	"syscall"
	"unsafe"
)

func (s *MmapVectorStore) mmap(size int64) error {
	// Map the full current file length. On Windows, passing a mapping length of 0
	// maps the entire *mapping object*, which was previously created with max size 0
	// (current file size at that moment). After file growth, that results in a view
	// that may not cover the new bytes and causes append writes to fail.
	//
	// Therefore we always create the mapping with the explicit file length (size),
	// and map exactly that many bytes.
	if size <= 0 {
		return fmt.Errorf("invalid mmap size: %d", size)
	}

	hi := uint32(uint64(size) >> 32)
	lo := uint32(uint64(size) & 0xffffffff)

	h, err := syscall.CreateFileMapping(
		syscall.Handle(s.file.Fd()),
		nil,
		syscall.PAGE_READWRITE,
		hi,
		lo,
		nil,
	)
	if err != nil {
		return fmt.Errorf("CreateFileMapping failed: %w", err)
	}
	s.mapHandle = uintptr(h)

	addr, err := syscall.MapViewOfFile(h, syscall.FILE_MAP_WRITE, 0, 0, uintptr(size))
	if err != nil {
		syscall.CloseHandle(h)
		s.mapHandle = 0
		return fmt.Errorf("MapViewOfFile failed: %w", err)
	}

	s.viewHandle = addr
	s.mapped = unsafe.Slice((*byte)(unsafe.Pointer(addr)), int(size))
	return nil
}

func (s *MmapVectorStore) munmap() error {
	if s.viewHandle != 0 {
		_ = syscall.UnmapViewOfFile(s.viewHandle)
		s.viewHandle = 0
	}
	if s.mapHandle != 0 {
		_ = syscall.CloseHandle(syscall.Handle(s.mapHandle))
		s.mapHandle = 0
	}
	s.mapped = nil
	return nil
}
