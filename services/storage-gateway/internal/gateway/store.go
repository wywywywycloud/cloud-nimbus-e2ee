package gateway

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"hash/fnv"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

var (
	ErrNotFound  = errors.New("not found")
	ErrConflict  = errors.New("conflict")
	ErrForbidden = errors.New("forbidden")
	ErrTooLarge  = errors.New("too large")
	ErrInvalid   = errors.New("invalid input")
)

type UploadState string

const (
	UploadActive   UploadState = "active"
	UploadComplete UploadState = "complete"
	UploadAborted  UploadState = "aborted"
)

type PartMetadata struct {
	Number int    `json:"number"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}

type UploadMetadata struct {
	Version        int                     `json:"version"`
	UploadID       string                  `json:"upload_id"`
	ObjectKey      string                  `json:"object_key"`
	TokenID        string                  `json:"token_id"`
	TokenExpiresAt time.Time               `json:"token_expires_at,omitempty"`
	Filename       string                  `json:"filename"`
	ContentType    string                  `json:"content_type"`
	DeclaredSize   int64                   `json:"declared_size"`
	ChunkSize      int64                   `json:"chunk_size"`
	State          UploadState             `json:"state"`
	Parts          map[string]PartMetadata `json:"parts"`
	CreatedAt      time.Time               `json:"created_at"`
	UpdatedAt      time.Time               `json:"updated_at"`
}

type grantRecord struct {
	Version   int            `json:"version"`
	TokenID   string         `json:"token_id"`
	Upload    UploadMetadata `json:"upload"`
	CleanedAt *time.Time     `json:"cleaned_at,omitempty"`
}

type CleanupStats struct {
	UploadsRemoved    int
	TombstonesRemoved int
}

type ObjectMetadata struct {
	Version     int       `json:"version"`
	ObjectKey   string    `json:"object_key"`
	Filename    string    `json:"filename"`
	ContentType string    `json:"content_type"`
	Size        int64     `json:"size"`
	CreatedAt   time.Time `json:"created_at"`
}

type LocalStore struct {
	root           string
	maxObjectBytes int64
	maxChunkBytes  int64
	maxParts       int
	locks          [64]sync.Mutex
	grantLocks     [64]sync.Mutex
}

func NewLocalStore(root string, maxObjectBytes, maxChunkBytes int64, maxParts int) (*LocalStore, error) {
	if root == "" || maxObjectBytes <= 0 || maxChunkBytes <= 0 || maxChunkBytes > maxObjectBytes || maxParts <= 0 {
		return nil, ErrInvalid
	}
	store := &LocalStore{root: root, maxObjectBytes: maxObjectBytes, maxChunkBytes: maxChunkBytes, maxParts: maxParts}
	for _, dir := range []string{store.uploadsRoot(), store.objectsRoot(), store.objectMetadataRoot(), store.grantsRoot()} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return nil, fmt.Errorf("create storage directory: %w", err)
		}
	}
	return store, nil
}

func (s *LocalStore) Initiate(tokenID string, tokenExpiresAt time.Time, filename, contentType string, declaredSize int64) (UploadMetadata, bool, error) {
	if tokenID == "" || len(tokenID) > 128 || declaredSize < 0 {
		return UploadMetadata{}, false, ErrInvalid
	}
	if declaredSize > s.maxObjectBytes {
		return UploadMetadata{}, false, ErrTooLarge
	}
	partsRequired := int64(0)
	if declaredSize > 0 {
		partsRequired = (declaredSize + s.maxChunkBytes - 1) / s.maxChunkBytes
	}
	if partsRequired > int64(s.maxParts) {
		return UploadMetadata{}, false, ErrTooLarge
	}
	filename = strings.TrimSpace(filepath.Base(filename))
	if filename == "" || filename == "." || len(filename) > 255 || strings.ContainsAny(filename, "\r\n") {
		return UploadMetadata{}, false, ErrInvalid
	}
	if len(contentType) > 255 || strings.ContainsAny(contentType, "\r\n") {
		return UploadMetadata{}, false, ErrInvalid
	}
	tokenExpiresAt = tokenExpiresAt.UTC()
	grantLock := s.grantLockFor(tokenID)
	grantLock.Lock()
	defer grantLock.Unlock()

	record, err := s.loadGrant(tokenID)
	if err == nil {
		if record.CleanedAt != nil {
			return UploadMetadata{}, false, ErrConflict
		}
		if record.Upload.Filename != filename || record.Upload.ContentType != contentType || record.Upload.DeclaredSize != declaredSize {
			return UploadMetadata{}, false, ErrConflict
		}
		meta, loadErr := s.loadUpload(record.Upload.UploadID)
		if loadErr == nil {
			return meta, false, nil
		}
		if !errors.Is(loadErr, ErrNotFound) {
			return UploadMetadata{}, false, loadErr
		}
		if err := s.persistInitialUpload(record.Upload); err != nil {
			return UploadMetadata{}, false, err
		}
		return record.Upload, false, nil
	}
	if !errors.Is(err, ErrNotFound) {
		return UploadMetadata{}, false, err
	}
	now := time.Now().UTC()
	meta := UploadMetadata{
		Version: 1, UploadID: randomHex(16), ObjectKey: randomHex(32), TokenID: tokenID,
		TokenExpiresAt: tokenExpiresAt, Filename: filename, ContentType: contentType, DeclaredSize: declaredSize,
		ChunkSize: s.maxChunkBytes, State: UploadActive, Parts: make(map[string]PartMetadata),
		CreatedAt: now, UpdatedAt: now,
	}
	record = grantRecord{Version: 1, TokenID: tokenID, Upload: meta}
	if err := atomicWriteJSON(s.grantPath(tokenID), record); err != nil {
		return UploadMetadata{}, false, err
	}
	if err := s.persistInitialUpload(meta); err != nil {
		return UploadMetadata{}, false, err
	}
	return meta, true, nil
}

func (s *LocalStore) persistInitialUpload(meta UploadMetadata) error {
	if err := os.MkdirAll(s.partsDir(meta.UploadID), 0o700); err != nil {
		return fmt.Errorf("create upload: %w", err)
	}
	if err := atomicWriteJSON(s.uploadMetadataPath(meta.UploadID), meta); err != nil {
		return err
	}
	return nil
}

func (s *LocalStore) GetUpload(uploadID, tokenID string) (UploadMetadata, error) {
	if !validUploadID(uploadID) {
		return UploadMetadata{}, ErrNotFound
	}
	meta, err := s.loadUpload(uploadID)
	if err != nil {
		return UploadMetadata{}, err
	}
	if meta.TokenID != tokenID {
		return UploadMetadata{}, ErrForbidden
	}
	return meta, nil
}

func (s *LocalStore) PutPart(uploadID, tokenID string, number int, body io.Reader, declaredLength int64) (PartMetadata, error) {
	if number < 1 || number > s.maxParts || declaredLength == 0 || declaredLength > s.maxChunkBytes {
		return PartMetadata{}, ErrInvalid
	}
	meta, err := s.GetUpload(uploadID, tokenID)
	if err != nil {
		return PartMetadata{}, err
	}
	if meta.State != UploadActive {
		return PartMetadata{}, ErrConflict
	}
	temp, err := os.CreateTemp(s.partsDir(uploadID), ".incoming-*")
	if err != nil {
		return PartMetadata{}, fmt.Errorf("create part: %w", err)
	}
	tempName := temp.Name()
	defer os.Remove(tempName)
	if err := temp.Chmod(0o600); err != nil {
		_ = temp.Close()
		return PartMetadata{}, err
	}
	hash := sha256.New()
	written, copyErr := io.Copy(io.MultiWriter(temp, hash), io.LimitReader(body, s.maxChunkBytes+1))
	if copyErr != nil {
		_ = temp.Close()
		return PartMetadata{}, fmt.Errorf("write part: %w", copyErr)
	}
	if written == 0 || written > s.maxChunkBytes || (declaredLength >= 0 && written != declaredLength) {
		_ = temp.Close()
		return PartMetadata{}, ErrTooLarge
	}
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return PartMetadata{}, err
	}
	if err := temp.Close(); err != nil {
		return PartMetadata{}, err
	}

	lock := s.lockFor(uploadID)
	lock.Lock()
	defer lock.Unlock()
	meta, err = s.loadUpload(uploadID)
	if err != nil {
		return PartMetadata{}, err
	}
	if meta.TokenID != tokenID {
		return PartMetadata{}, ErrForbidden
	}
	if meta.State != UploadActive {
		return PartMetadata{}, ErrConflict
	}
	part := PartMetadata{Number: number, Size: written, SHA256: hex.EncodeToString(hash.Sum(nil))}
	if err := os.Rename(tempName, s.partPath(uploadID, number)); err != nil {
		return PartMetadata{}, fmt.Errorf("commit part: %w", err)
	}
	if err := syncDirectory(s.partsDir(uploadID)); err != nil {
		return PartMetadata{}, err
	}
	meta.Parts[fmt.Sprint(number)] = part
	meta.UpdatedAt = time.Now().UTC()
	if err := atomicWriteJSON(s.uploadMetadataPath(uploadID), meta); err != nil {
		return PartMetadata{}, err
	}
	return part, nil
}

func (s *LocalStore) Complete(uploadID, tokenID string) (ObjectMetadata, error) {
	if !validUploadID(uploadID) {
		return ObjectMetadata{}, ErrNotFound
	}
	lock := s.lockFor(uploadID)
	lock.Lock()
	defer lock.Unlock()
	meta, err := s.loadUpload(uploadID)
	if err != nil {
		return ObjectMetadata{}, err
	}
	if meta.TokenID != tokenID {
		return ObjectMetadata{}, ErrForbidden
	}
	if meta.State == UploadComplete {
		return s.LoadObjectMetadata(meta.ObjectKey)
	}
	if meta.State != UploadActive {
		return ObjectMetadata{}, ErrConflict
	}
	expectedParts := 0
	if meta.DeclaredSize > 0 {
		expectedParts = int((meta.DeclaredSize + meta.ChunkSize - 1) / meta.ChunkSize)
	}
	if len(meta.Parts) != expectedParts {
		return ObjectMetadata{}, ErrConflict
	}
	for number := 1; number <= expectedParts; number++ {
		part, ok := meta.Parts[fmt.Sprint(number)]
		expectedSize := meta.ChunkSize
		if number == expectedParts {
			expectedSize = meta.DeclaredSize - int64(number-1)*meta.ChunkSize
		}
		if !ok || part.Size != expectedSize {
			return ObjectMetadata{}, ErrConflict
		}
	}

	objectPath := s.objectPath(meta.ObjectKey)
	if err := os.MkdirAll(filepath.Dir(objectPath), 0o700); err != nil {
		return ObjectMetadata{}, err
	}
	temp, err := os.CreateTemp(filepath.Dir(objectPath), ".assembling-*")
	if err != nil {
		return ObjectMetadata{}, err
	}
	tempName := temp.Name()
	defer os.Remove(tempName)
	if err := temp.Chmod(0o600); err != nil {
		_ = temp.Close()
		return ObjectMetadata{}, err
	}
	var total int64
	for number := 1; number <= expectedParts; number++ {
		partFile, err := os.Open(s.partPath(uploadID, number))
		if err != nil {
			_ = temp.Close()
			return ObjectMetadata{}, ErrConflict
		}
		copied, copyErr := io.Copy(temp, partFile)
		closeErr := partFile.Close()
		if copyErr != nil || closeErr != nil {
			_ = temp.Close()
			return ObjectMetadata{}, fmt.Errorf("assemble object: %v %v", copyErr, closeErr)
		}
		total += copied
	}
	if total != meta.DeclaredSize {
		_ = temp.Close()
		return ObjectMetadata{}, ErrConflict
	}
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return ObjectMetadata{}, err
	}
	if err := temp.Close(); err != nil {
		return ObjectMetadata{}, err
	}
	if err := os.Rename(tempName, objectPath); err != nil {
		return ObjectMetadata{}, err
	}
	if err := syncDirectory(filepath.Dir(objectPath)); err != nil {
		return ObjectMetadata{}, err
	}
	objectMeta := ObjectMetadata{
		Version: 1, ObjectKey: meta.ObjectKey, Filename: meta.Filename,
		ContentType: meta.ContentType, Size: total, CreatedAt: time.Now().UTC(),
	}
	if err := atomicWriteJSON(s.objectMetadataPath(meta.ObjectKey), objectMeta); err != nil {
		return ObjectMetadata{}, err
	}
	meta.State = UploadComplete
	meta.UpdatedAt = time.Now().UTC()
	if err := atomicWriteJSON(s.uploadMetadataPath(uploadID), meta); err != nil {
		return ObjectMetadata{}, err
	}
	_ = os.RemoveAll(s.partsDir(uploadID))
	return objectMeta, nil
}

func (s *LocalStore) Abort(uploadID, tokenID string) error {
	if !validUploadID(uploadID) {
		return ErrNotFound
	}
	lock := s.lockFor(uploadID)
	lock.Lock()
	defer lock.Unlock()
	meta, err := s.loadUpload(uploadID)
	if err != nil {
		return err
	}
	if meta.TokenID != tokenID {
		return ErrForbidden
	}
	if meta.State == UploadComplete {
		return ErrConflict
	}
	if meta.State == UploadAborted {
		return nil
	}
	meta.State = UploadAborted
	meta.UpdatedAt = time.Now().UTC()
	if err := atomicWriteJSON(s.uploadMetadataPath(uploadID), meta); err != nil {
		return err
	}
	return os.RemoveAll(s.partsDir(uploadID))
}

func (s *LocalStore) CleanupStale(now time.Time, uploadTTL time.Duration) (CleanupStats, error) {
	var stats CleanupStats
	if uploadTTL <= 0 {
		return stats, ErrInvalid
	}
	now = now.UTC()
	entries, err := os.ReadDir(s.uploadsRoot())
	if err != nil {
		return stats, err
	}
	var cleanupErrors []error
	for _, entry := range entries {
		if !entry.IsDir() || !validUploadID(entry.Name()) {
			continue
		}
		removed, cleanupErr := s.cleanupUpload(entry.Name(), now, uploadTTL)
		if cleanupErr != nil {
			cleanupErrors = append(cleanupErrors, fmt.Errorf("cleanup upload %s: %w", entry.Name(), cleanupErr))
			continue
		}
		if removed {
			stats.UploadsRemoved++
		}
	}
	removedTombstones, err := s.cleanupExpiredTombstones(now)
	stats.TombstonesRemoved = removedTombstones
	if err != nil {
		cleanupErrors = append(cleanupErrors, err)
	}
	return stats, errors.Join(cleanupErrors...)
}

func (s *LocalStore) cleanupUpload(uploadID string, now time.Time, uploadTTL time.Duration) (bool, error) {
	meta, err := s.loadUpload(uploadID)
	if errors.Is(err, ErrNotFound) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	grantLock := s.grantLockFor(meta.TokenID)
	grantLock.Lock()
	defer grantLock.Unlock()
	uploadLock := s.lockFor(uploadID)
	uploadLock.Lock()
	defer uploadLock.Unlock()

	meta, err = s.loadUpload(uploadID)
	if errors.Is(err, ErrNotFound) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if meta.State == UploadComplete {
		return false, nil
	}
	expired := !meta.TokenExpiresAt.IsZero() && !now.Before(meta.TokenExpiresAt)
	stale := !now.Before(meta.UpdatedAt.Add(uploadTTL))
	if !expired && !stale {
		return false, nil
	}

	record, err := s.loadGrant(meta.TokenID)
	if errors.Is(err, ErrNotFound) {
		record = grantRecord{Version: 1, TokenID: meta.TokenID, Upload: meta}
	} else if err != nil {
		return false, err
	}
	if record.Upload.UploadID != uploadID {
		return false, ErrConflict
	}
	if record.CleanedAt == nil {
		cleanedAt := now
		record.CleanedAt = &cleanedAt
		if err := atomicWriteJSON(s.grantPath(meta.TokenID), record); err != nil {
			return false, err
		}
	}
	if err := os.RemoveAll(s.uploadDir(uploadID)); err != nil {
		return false, err
	}
	if err := syncDirectory(s.uploadsRoot()); err != nil {
		return false, err
	}
	return true, nil
}

func (s *LocalStore) cleanupExpiredTombstones(now time.Time) (int, error) {
	entries, err := os.ReadDir(s.grantsRoot())
	if err != nil {
		return 0, err
	}
	removed := 0
	var cleanupErrors []error
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		path := filepath.Join(s.grantsRoot(), entry.Name())
		var record grantRecord
		if err := readJSON(path, &record); err != nil {
			cleanupErrors = append(cleanupErrors, fmt.Errorf("read grant %s: %w", entry.Name(), err))
			continue
		}
		if filepath.Base(s.grantPath(record.TokenID)) != entry.Name() {
			cleanupErrors = append(cleanupErrors, fmt.Errorf("grant filename does not match token id: %s", entry.Name()))
			continue
		}
		lock := s.grantLockFor(record.TokenID)
		lock.Lock()
		current, loadErr := s.loadGrant(record.TokenID)
		if loadErr == nil && current.CleanedAt == nil && !current.Upload.TokenExpiresAt.IsZero() && !now.Before(current.Upload.TokenExpiresAt) {
			if _, statErr := os.Stat(s.uploadMetadataPath(current.Upload.UploadID)); errors.Is(statErr, os.ErrNotExist) {
				cleanedAt := now
				current.CleanedAt = &cleanedAt
				loadErr = atomicWriteJSON(s.grantPath(current.TokenID), current)
			} else if statErr != nil {
				loadErr = statErr
			}
		}
		if loadErr == nil && current.CleanedAt != nil {
			loadErr = os.RemoveAll(s.uploadDir(current.Upload.UploadID))
			if loadErr == nil {
				loadErr = syncDirectory(s.uploadsRoot())
			}
			if loadErr == nil && !current.Upload.TokenExpiresAt.IsZero() && !now.Before(current.Upload.TokenExpiresAt) {
				loadErr = os.Remove(s.grantPath(record.TokenID))
				if loadErr == nil {
					loadErr = syncDirectory(s.grantsRoot())
					removed++
				}
			}
		}
		lock.Unlock()
		if loadErr != nil && !errors.Is(loadErr, ErrNotFound) && !errors.Is(loadErr, os.ErrNotExist) {
			cleanupErrors = append(cleanupErrors, fmt.Errorf("remove grant %s: %w", entry.Name(), loadErr))
		}
	}
	return removed, errors.Join(cleanupErrors...)
}

func (s *LocalStore) LoadObjectMetadata(objectKey string) (ObjectMetadata, error) {
	var meta ObjectMetadata
	if !validObjectKey(objectKey) {
		return meta, ErrNotFound
	}
	if err := readJSON(s.objectMetadataPath(objectKey), &meta); err != nil {
		return meta, err
	}
	if meta.ObjectKey != objectKey || meta.Size < 0 {
		return ObjectMetadata{}, ErrInvalid
	}
	return meta, nil
}

func (s *LocalStore) OpenObject(objectKey string) (*os.File, ObjectMetadata, error) {
	meta, err := s.LoadObjectMetadata(objectKey)
	if err != nil {
		return nil, ObjectMetadata{}, err
	}
	file, err := os.Open(s.objectPath(objectKey))
	if errors.Is(err, os.ErrNotExist) {
		return nil, ObjectMetadata{}, ErrNotFound
	}
	if err != nil {
		return nil, ObjectMetadata{}, err
	}
	return file, meta, nil
}

func (s *LocalStore) SortedParts(meta UploadMetadata) []PartMetadata {
	parts := make([]PartMetadata, 0, len(meta.Parts))
	for _, part := range meta.Parts {
		parts = append(parts, part)
	}
	sort.Slice(parts, func(i, j int) bool { return parts[i].Number < parts[j].Number })
	return parts
}

func (s *LocalStore) loadUpload(uploadID string) (UploadMetadata, error) {
	var meta UploadMetadata
	if err := readJSON(s.uploadMetadataPath(uploadID), &meta); err != nil {
		return meta, err
	}
	if meta.UploadID != uploadID || !validObjectKey(meta.ObjectKey) || meta.Parts == nil {
		return UploadMetadata{}, ErrInvalid
	}
	return meta, nil
}

func (s *LocalStore) loadGrant(tokenID string) (grantRecord, error) {
	var record grantRecord
	if err := readJSON(s.grantPath(tokenID), &record); err != nil {
		return record, err
	}
	if record.Version != 1 || record.TokenID != tokenID || record.Upload.TokenID != tokenID || !validUploadID(record.Upload.UploadID) || !validObjectKey(record.Upload.ObjectKey) {
		return grantRecord{}, ErrInvalid
	}
	return record, nil
}

func readJSON(path string, destination any) error {
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return ErrNotFound
	}
	if err != nil {
		return err
	}
	defer file.Close()
	decoder := json.NewDecoder(io.LimitReader(file, 2*1024*1024))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return fmt.Errorf("read metadata: %w", err)
	}
	return nil
}

func atomicWriteJSON(path string, value any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(path), ".metadata-*")
	if err != nil {
		return err
	}
	tempName := temp.Name()
	defer os.Remove(tempName)
	if err := temp.Chmod(0o600); err != nil {
		_ = temp.Close()
		return err
	}
	encoder := json.NewEncoder(temp)
	if err := encoder.Encode(value); err != nil {
		_ = temp.Close()
		return err
	}
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tempName, path); err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(path))
}

func syncDirectory(path string) error {
	directory, err := os.Open(path)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

func randomHex(bytesCount int) string {
	buffer := make([]byte, bytesCount)
	if _, err := io.ReadFull(rand.Reader, buffer); err != nil {
		panic("crypto/rand unavailable: " + err.Error())
	}
	return hex.EncodeToString(buffer)
}

func validUploadID(value string) bool  { return validHex(value, 32) }
func validObjectKey(value string) bool { return validHex(value, 64) }

func validHex(value string, length int) bool {
	if len(value) != length {
		return false
	}
	for _, character := range value {
		if !((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f')) {
			return false
		}
	}
	return true
}

func (s *LocalStore) lockFor(identifier string) *sync.Mutex {
	hash := fnv.New32a()
	_, _ = hash.Write([]byte(identifier))
	return &s.locks[int(hash.Sum32())%len(s.locks)]
}

func (s *LocalStore) grantLockFor(tokenID string) *sync.Mutex {
	hash := fnv.New32a()
	_, _ = hash.Write([]byte(tokenID))
	return &s.grantLocks[int(hash.Sum32())%len(s.grantLocks)]
}

func (s *LocalStore) uploadsRoot() string        { return filepath.Join(s.root, "uploads") }
func (s *LocalStore) objectsRoot() string        { return filepath.Join(s.root, "objects") }
func (s *LocalStore) objectMetadataRoot() string { return filepath.Join(s.root, "object-metadata") }
func (s *LocalStore) uploadDir(id string) string { return filepath.Join(s.uploadsRoot(), id) }
func (s *LocalStore) partsDir(id string) string  { return filepath.Join(s.uploadDir(id), "parts") }
func (s *LocalStore) uploadMetadataPath(id string) string {
	return filepath.Join(s.uploadDir(id), "metadata.json")
}
func (s *LocalStore) partPath(id string, number int) string {
	return filepath.Join(s.partsDir(id), fmt.Sprintf("%08d.part", number))
}
func (s *LocalStore) objectPath(key string) string {
	return filepath.Join(s.objectsRoot(), key[:2], key)
}
func (s *LocalStore) objectMetadataPath(key string) string {
	return filepath.Join(s.objectMetadataRoot(), key[:2], key+".json")
}
func (s *LocalStore) grantsRoot() string { return filepath.Join(s.root, "upload-grants") }
func (s *LocalStore) grantPath(tokenID string) string {
	digest := sha256.Sum256([]byte(tokenID))
	return filepath.Join(s.grantsRoot(), hex.EncodeToString(digest[:])+".json")
}
