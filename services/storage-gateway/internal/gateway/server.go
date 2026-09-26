package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type Server struct {
	cfg    Config
	store  *LocalStore
	logger *slog.Logger
	mux    *http.ServeMux
}

func NewServer(cfg Config, logger *slog.Logger) (*Server, error) {
	cfg = cfg.withDefaults()
	store, err := NewLocalStore(cfg.StorageRoot, cfg.MaxObjectBytes, cfg.MaxChunkBytes, cfg.MaxParts)
	if err != nil {
		return nil, err
	}
	if logger == nil {
		logger = slog.Default()
	}
	server := &Server{cfg: cfg, store: store, logger: logger, mux: http.NewServeMux()}
	server.routes()
	return server, nil
}

func (s *Server) Handler() http.Handler {
	return s.recoverPanics(s.securityHeaders(s.mux))
}

func (s *Server) StartCleanup(ctx context.Context) {
	go func() {
		s.cleanupOnce()
		ticker := time.NewTicker(s.cfg.CleanupPeriod)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				s.cleanupOnce()
			}
		}
	}()
}

func (s *Server) cleanupOnce() {
	stats, err := s.store.CleanupStale(time.Now().UTC(), s.cfg.UploadTTL)
	if err != nil {
		s.logger.Error("cleanup uploads", "error", err)
		return
	}
	if stats.UploadsRemoved > 0 || stats.TombstonesRemoved > 0 {
		s.logger.Info("cleaned uploads", "uploads", stats.UploadsRemoved, "tombstones", stats.TombstonesRemoved)
	}
}

func (s *Server) routes() {
	s.mux.HandleFunc("/healthz", s.healthz)
	s.mux.HandleFunc("/v1/uploads", s.uploadCollection)
	s.mux.HandleFunc("/v1/uploads/", s.uploadItem)
	s.mux.HandleFunc("/v1/objects/", s.downloadObject)
}

func (s *Server) healthz(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w, http.MethodGet)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) uploadCollection(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/v1/uploads" {
		writeError(w, http.StatusNotFound, "not_found", "resource not found")
		return
	}
	if r.Method != http.MethodPost {
		methodNotAllowed(w, http.MethodPost)
		return
	}
	claims, ok := s.authorize(r, "upload")
	if !ok {
		writeError(w, http.StatusUnauthorized, "invalid_token", "valid upload token required")
		return
	}
	var request struct {
		Filename    string `json:"filename"`
		ContentType string `json:"content_type"`
		Size        int64  `json:"size"`
	}
	r.Body = http.MaxBytesReader(w, r.Body, 64*1024)
	if err := decodeJSON(r.Body, &request); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_request", err.Error())
		return
	}
	if claims.MaxBytes > 0 && request.Size > claims.MaxBytes {
		writeError(w, http.StatusRequestEntityTooLarge, "size_limit", "object exceeds token limit")
		return
	}
	meta, _, err := s.store.Initiate(claims.TokenID, time.Unix(claims.ExpiresAt, 0).Add(s.cfg.TokenClockSkew), request.Filename, request.ContentType, request.Size)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"upload_id": meta.UploadID, "object_key": meta.ObjectKey,
		"chunk_size": meta.ChunkSize, "max_parts": s.cfg.MaxParts,
	})
}

func (s *Server) uploadItem(w http.ResponseWriter, r *http.Request) {
	segments := splitPath(r.URL.Path)
	if len(segments) < 3 || segments[0] != "v1" || segments[1] != "uploads" || !validUploadID(segments[2]) {
		writeError(w, http.StatusNotFound, "not_found", "resource not found")
		return
	}
	claims, ok := s.authorize(r, "upload")
	if !ok {
		writeError(w, http.StatusUnauthorized, "invalid_token", "valid upload token required")
		return
	}
	uploadID := segments[2]
	switch {
	case len(segments) == 3 && r.Method == http.MethodGet:
		s.uploadStatus(w, uploadID, claims.TokenID)
	case len(segments) == 3 && r.Method == http.MethodDelete:
		s.abortUpload(w, uploadID, claims.TokenID)
	case len(segments) == 4 && segments[3] == "complete" && r.Method == http.MethodPost:
		s.completeUpload(w, uploadID, claims.TokenID)
	case len(segments) == 5 && segments[3] == "parts" && r.Method == http.MethodPut:
		partNumber, err := strconv.Atoi(segments[4])
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid_part", "part number must be an integer")
			return
		}
		s.putPart(w, r, uploadID, claims.TokenID, partNumber)
	default:
		writeError(w, http.StatusNotFound, "not_found", "resource not found")
	}
}

func (s *Server) uploadStatus(w http.ResponseWriter, uploadID, tokenID string) {
	meta, err := s.store.GetUpload(uploadID, tokenID)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	parts := s.store.SortedParts(meta)
	var received int64
	for _, part := range parts {
		received += part.Size
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"upload_id": meta.UploadID, "object_key": meta.ObjectKey, "state": meta.State,
		"declared_size": meta.DeclaredSize, "received_bytes": received, "parts": parts,
	})
}

func (s *Server) putPart(w http.ResponseWriter, r *http.Request, uploadID, tokenID string, partNumber int) {
	if r.ContentLength > s.cfg.MaxChunkBytes {
		writeError(w, http.StatusRequestEntityTooLarge, "chunk_limit", "part exceeds configured chunk limit")
		return
	}
	part, err := s.store.PutPart(uploadID, tokenID, partNumber, r.Body, r.ContentLength)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, part)
}

func (s *Server) completeUpload(w http.ResponseWriter, uploadID, tokenID string) {
	object, err := s.store.Complete(uploadID, tokenID)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, object)
}

func (s *Server) abortUpload(w http.ResponseWriter, uploadID, tokenID string) {
	if err := s.store.Abort(uploadID, tokenID); err != nil {
		s.writeStoreError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) downloadObject(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		methodNotAllowed(w, http.MethodGet, http.MethodHead)
		return
	}
	segments := splitPath(r.URL.Path)
	if len(segments) != 3 || segments[0] != "v1" || segments[1] != "objects" || !validObjectKey(segments[2]) {
		writeError(w, http.StatusNotFound, "not_found", "resource not found")
		return
	}
	claims, ok := s.authorize(r, "download")
	if !ok || claims.ObjectKey != segments[2] {
		writeError(w, http.StatusUnauthorized, "invalid_token", "valid download token required")
		return
	}
	file, meta, err := s.store.OpenObject(segments[2])
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	defer file.Close()
	w.Header().Set("Accept-Ranges", "bytes")
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", mime.FormatMediaType("attachment", map[string]string{"filename": meta.Filename}))
	w.Header().Set("X-Content-Type-Options", "nosniff")

	start, length, status := int64(0), meta.Size, http.StatusOK
	if rangeHeader := r.Header.Get("Range"); rangeHeader != "" {
		selected, rangeErr := parseSingleRange(rangeHeader, meta.Size)
		if rangeErr != nil {
			w.Header().Set("Content-Range", fmt.Sprintf("bytes */%d", meta.Size))
			writeError(w, http.StatusRequestedRangeNotSatisfiable, "invalid_range", "range cannot be satisfied")
			return
		}
		start, length, status = selected.start, selected.end-selected.start+1, http.StatusPartialContent
		w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", selected.start, selected.end, meta.Size))
	}
	w.Header().Set("Content-Length", strconv.FormatInt(length, 10))
	w.WriteHeader(status)
	if r.Method == http.MethodHead {
		return
	}
	if _, err := file.Seek(start, io.SeekStart); err != nil {
		s.logger.Error("seek object", "error", err, "object_key", meta.ObjectKey)
		return
	}
	if _, err := io.CopyN(w, file, length); err != nil {
		s.logger.Warn("stream interrupted", "error", err, "object_key", meta.ObjectKey)
	}
}

func (s *Server) authorize(r *http.Request, expectedAction string) (TokenClaims, bool) {
	raw := ""
	if header := r.Header.Get("Authorization"); strings.HasPrefix(header, "Bearer ") {
		raw = strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))
	}
	if raw == "" && expectedAction == "download" {
		raw = r.URL.Query().Get("token")
	}
	claims, err := VerifyToken(s.cfg.HMACSecret, raw, time.Now(), s.cfg.TokenClockSkew)
	return claims, err == nil && claims.Action == expectedAction
}

func (s *Server) writeStoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrNotFound):
		writeError(w, http.StatusNotFound, "not_found", "resource not found")
	case errors.Is(err, ErrForbidden):
		writeError(w, http.StatusForbidden, "forbidden", "token does not own this upload")
	case errors.Is(err, ErrConflict):
		writeError(w, http.StatusConflict, "upload_conflict", "upload state or parts do not permit this operation")
	case errors.Is(err, ErrTooLarge):
		writeError(w, http.StatusRequestEntityTooLarge, "size_limit", "configured size limit exceeded")
	case errors.Is(err, ErrInvalid):
		writeError(w, http.StatusBadRequest, "invalid_request", "invalid upload parameters")
	default:
		s.logger.Error("storage operation failed", "error", err)
		writeError(w, http.StatusInternalServerError, "internal_error", "storage operation failed")
	}
}

func (s *Server) securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		next.ServeHTTP(w, r)
	})
}

func (s *Server) recoverPanics(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recovered := recover(); recovered != nil {
				s.logger.Error("request panic", "panic", recovered)
				writeError(w, http.StatusInternalServerError, "internal_error", "unexpected server error")
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func decodeJSON(reader io.Reader, destination any) error {
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return errors.New("request body must be valid JSON")
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("request body must contain one JSON object")
	}
	return nil
}

func splitPath(path string) []string {
	trimmed := strings.Trim(path, "/")
	if trimmed == "" {
		return nil
	}
	return strings.Split(trimmed, "/")
}

func methodNotAllowed(w http.ResponseWriter, methods ...string) {
	w.Header().Set("Allow", strings.Join(methods, ", "))
	writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method not allowed")
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": message}})
}
