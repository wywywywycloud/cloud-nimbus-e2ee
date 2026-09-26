package gateway

import (
	"errors"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestConcurrentInitiateCreatesOneSession(t *testing.T) {
	root := t.TempDir()
	store, err := NewLocalStore(root, 16, 4, 4)
	if err != nil {
		t.Fatal(err)
	}
	expiresAt := time.Now().Add(time.Hour)
	const callers = 32
	var created atomic.Int32
	ids := make(chan string, callers)
	errs := make(chan error, callers)
	var wait sync.WaitGroup
	for range callers {
		wait.Add(1)
		go func() {
			defer wait.Done()
			meta, wasCreated, err := store.Initiate("concurrent-jti", expiresAt, "file.bin", "application/octet-stream", 8)
			if err != nil {
				errs <- err
				return
			}
			if wasCreated {
				created.Add(1)
			}
			ids <- meta.UploadID
		}()
	}
	wait.Wait()
	close(ids)
	close(errs)
	for err := range errs {
		t.Errorf("initiate: %v", err)
	}
	var uploadID string
	for id := range ids {
		if uploadID == "" {
			uploadID = id
		}
		if id != uploadID {
			t.Fatalf("multiple upload ids: %q and %q", uploadID, id)
		}
	}
	if created.Load() != 1 {
		t.Fatalf("created %d sessions, want 1", created.Load())
	}
	entries, err := os.ReadDir(store.uploadsRoot())
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("upload directories=%d, want 1", len(entries))
	}
}

func TestInitiateRepairsMissingUploadFromGrantRecord(t *testing.T) {
	store, err := NewLocalStore(t.TempDir(), 16, 4, 4)
	if err != nil {
		t.Fatal(err)
	}
	expiresAt := time.Now().Add(time.Hour)
	initial, _, err := store.Initiate("repair-jti", expiresAt, "file.bin", "", 4)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.RemoveAll(store.uploadDir(initial.UploadID)); err != nil {
		t.Fatal(err)
	}
	repaired, created, err := store.Initiate("repair-jti", expiresAt, "file.bin", "", 4)
	if err != nil {
		t.Fatal(err)
	}
	if created || repaired.UploadID != initial.UploadID || repaired.ObjectKey != initial.ObjectKey {
		t.Fatalf("grant repair changed identity: created=%v initial=%#v repaired=%#v", created, initial, repaired)
	}
	if _, err := store.GetUpload(initial.UploadID, initial.TokenID); err != nil {
		t.Fatalf("repaired upload cannot be loaded: %v", err)
	}
}

func TestCleanupRemovesStaleUploadAndRetainsGrantTombstone(t *testing.T) {
	store, err := NewLocalStore(t.TempDir(), 16, 4, 4)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Truncate(time.Second)
	expiresAt := now.Add(2 * time.Hour)
	meta, _, err := store.Initiate("stale-jti", expiresAt, "stale.bin", "", 4)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.PutPart(meta.UploadID, meta.TokenID, 1, strings.NewReader("data"), 4); err != nil {
		t.Fatal(err)
	}
	meta, err = store.loadUpload(meta.UploadID)
	if err != nil {
		t.Fatal(err)
	}
	meta.UpdatedAt = now.Add(-2 * time.Hour)
	if err := atomicWriteJSON(store.uploadMetadataPath(meta.UploadID), meta); err != nil {
		t.Fatal(err)
	}

	stats, err := store.CleanupStale(now, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if stats.UploadsRemoved != 1 || stats.TombstonesRemoved != 0 {
		t.Fatalf("unexpected stats: %#v", stats)
	}
	if _, err := os.Stat(store.uploadDir(meta.UploadID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("upload directory still exists: %v", err)
	}
	record, err := store.loadGrant(meta.TokenID)
	if err != nil || record.CleanedAt == nil {
		t.Fatalf("missing cleanup tombstone: %#v %v", record, err)
	}
	if _, _, err := store.Initiate(meta.TokenID, expiresAt, meta.Filename, meta.ContentType, meta.DeclaredSize); !errors.Is(err, ErrConflict) {
		t.Fatalf("cleaned capability recreated upload: %v", err)
	}

	stats, err = store.CleanupStale(expiresAt.Add(time.Second), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if stats.TombstonesRemoved != 1 {
		t.Fatalf("expired tombstones removed=%d, want 1", stats.TombstonesRemoved)
	}
	if _, err := os.Stat(store.grantPath(meta.TokenID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expired tombstone still exists: %v", err)
	}
}

func TestCleanupRemovesExpiredButKeepsRecentUpload(t *testing.T) {
	store, err := NewLocalStore(t.TempDir(), 16, 4, 4)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	expired, _, err := store.Initiate("expired-jti", now.Add(-time.Minute), "expired.bin", "", 4)
	if err != nil {
		t.Fatal(err)
	}
	recent, _, err := store.Initiate("recent-jti", now.Add(time.Hour), "recent.bin", "", 4)
	if err != nil {
		t.Fatal(err)
	}
	stats, err := store.CleanupStale(now, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if stats.UploadsRemoved != 1 || stats.TombstonesRemoved != 1 {
		t.Fatalf("unexpected stats: %#v", stats)
	}
	if _, err := store.GetUpload(expired.UploadID, expired.TokenID); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expired upload still available: %v", err)
	}
	if _, err := store.GetUpload(recent.UploadID, recent.TokenID); err != nil {
		t.Fatalf("recent upload removed: %v", err)
	}
}

func TestCleanupRemovesExpiredGrantWithMissingMetadata(t *testing.T) {
	store, err := NewLocalStore(t.TempDir(), 16, 4, 4)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	meta, _, err := store.Initiate("orphaned-jti", now.Add(-time.Minute), "orphaned.bin", "", 4)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(store.uploadMetadataPath(meta.UploadID)); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(store.partPath(meta.UploadID, 1), []byte("data"), 0o600); err != nil {
		t.Fatal(err)
	}
	stats, err := store.CleanupStale(now, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if stats.TombstonesRemoved != 1 {
		t.Fatalf("unexpected stats: %#v", stats)
	}
	if _, err := os.Stat(store.uploadDir(meta.UploadID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("orphaned upload data still exists: %v", err)
	}
	if _, err := os.Stat(store.grantPath(meta.TokenID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expired grant still exists: %v", err)
	}
}
