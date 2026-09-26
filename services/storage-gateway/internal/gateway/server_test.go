package gateway

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type initiateResponse struct {
	UploadID  string `json:"upload_id"`
	ObjectKey string `json:"object_key"`
	ChunkSize int64  `json:"chunk_size"`
}

func TestResumableUploadDownloadRangeAndAbort(t *testing.T) {
	secret := []byte(strings.Repeat("g", 32))
	cfg := Config{
		StorageRoot: t.TempDir(), HMACSecret: secret,
		MaxObjectBytes: 16, MaxChunkBytes: 4, MaxParts: 4,
	}
	server, err := NewServer(cfg, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	uploadToken := mustToken(t, secret, TokenClaims{
		Action: "upload", ExpiresAt: time.Now().Add(time.Hour).Unix(), TokenID: "grant-1", MaxBytes: 12,
	})

	init := request(t, handler, http.MethodPost, "/v1/uploads", `{"filename":"hello.txt","content_type":"text/plain","size":7}`, uploadToken, nil)
	if init.Code != http.StatusCreated {
		t.Fatalf("initiate: %d %s", init.Code, init.Body.String())
	}
	var upload initiateResponse
	decodeResponse(t, init, &upload)
	if upload.ChunkSize != 4 || !validUploadID(upload.UploadID) || !validObjectKey(upload.ObjectKey) {
		t.Fatalf("unexpected initiate response: %#v", upload)
	}

	put1 := request(t, handler, http.MethodPut, "/v1/uploads/"+upload.UploadID+"/parts/1", "abcd", uploadToken, nil)
	put2 := request(t, handler, http.MethodPut, "/v1/uploads/"+upload.UploadID+"/parts/2", "efg", uploadToken, nil)
	if put1.Code != http.StatusCreated || put2.Code != http.StatusCreated {
		t.Fatalf("parts: %d/%d: %s %s", put1.Code, put2.Code, put1.Body.String(), put2.Body.String())
	}

	status := request(t, handler, http.MethodGet, "/v1/uploads/"+upload.UploadID, "", uploadToken, nil)
	if status.Code != http.StatusOK || !bytes.Contains(status.Body.Bytes(), []byte(`"received_bytes":7`)) {
		t.Fatalf("status: %d %s", status.Code, status.Body.String())
	}
	wrongUploadToken := mustToken(t, secret, TokenClaims{
		Action: "upload", ExpiresAt: time.Now().Add(time.Hour).Unix(), TokenID: "other-grant",
	})
	wrongStatus := request(t, handler, http.MethodGet, "/v1/uploads/"+upload.UploadID, "", wrongUploadToken, nil)
	if wrongStatus.Code != http.StatusForbidden {
		t.Fatalf("cross-token status returned %d", wrongStatus.Code)
	}

	complete := request(t, handler, http.MethodPost, "/v1/uploads/"+upload.UploadID+"/complete", "", uploadToken, nil)
	if complete.Code != http.StatusOK {
		t.Fatalf("complete: %d %s", complete.Code, complete.Body.String())
	}
	withoutToken := request(t, handler, http.MethodGet, "/v1/objects/"+upload.ObjectKey, "", "", nil)
	if withoutToken.Code != http.StatusUnauthorized {
		t.Fatalf("unsigned download returned %d", withoutToken.Code)
	}
	downloadToken := mustToken(t, secret, TokenClaims{
		Action: "download", ExpiresAt: time.Now().Add(time.Hour).Unix(), TokenID: "download-1", ObjectKey: upload.ObjectKey,
	})
	full := request(t, handler, http.MethodGet, "/v1/objects/"+upload.ObjectKey+"?token="+downloadToken, "", "", nil)
	if full.Code != http.StatusOK || full.Body.String() != "abcdefg" || full.Header().Get("Accept-Ranges") != "bytes" {
		t.Fatalf("download: %d %q", full.Code, full.Body.String())
	}
	ranged := request(t, handler, http.MethodGet, "/v1/objects/"+upload.ObjectKey+"?token="+downloadToken, "", "", map[string]string{"Range": "bytes=1-3"})
	if ranged.Code != http.StatusPartialContent || ranged.Body.String() != "bcd" || ranged.Header().Get("Content-Range") != "bytes 1-3/7" {
		t.Fatalf("range: %d %q %q", ranged.Code, ranged.Body.String(), ranged.Header().Get("Content-Range"))
	}
	head := request(t, handler, http.MethodHead, "/v1/objects/"+upload.ObjectKey+"?token="+downloadToken, "", "", nil)
	if head.Code != http.StatusOK || head.Body.Len() != 0 || head.Header().Get("Content-Length") != "7" {
		t.Fatalf("head: %d %d %#v", head.Code, head.Body.Len(), head.Header())
	}

	abortToken := mustToken(t, secret, TokenClaims{
		Action: "upload", ExpiresAt: time.Now().Add(time.Hour).Unix(), TokenID: "grant-2", MaxBytes: 12,
	})
	abortInit := request(t, handler, http.MethodPost, "/v1/uploads", `{"filename":"discard.bin","size":4}`, abortToken, nil)
	var abortUpload initiateResponse
	decodeResponse(t, abortInit, &abortUpload)
	abort := request(t, handler, http.MethodDelete, "/v1/uploads/"+abortUpload.UploadID, "", abortToken, nil)
	if abort.Code != http.StatusNoContent {
		t.Fatalf("abort: %d %s", abort.Code, abort.Body.String())
	}
	abortedStatus := request(t, handler, http.MethodGet, "/v1/uploads/"+abortUpload.UploadID, "", abortToken, nil)
	if abortedStatus.Code != http.StatusOK || !bytes.Contains(abortedStatus.Body.Bytes(), []byte(`"state":"aborted"`)) {
		t.Fatalf("aborted status: %d %s", abortedStatus.Code, abortedStatus.Body.String())
	}
}

func TestInitiateIsIdempotentPerTokenID(t *testing.T) {
	secret := []byte(strings.Repeat("i", 32))
	root := t.TempDir()
	cfg := Config{StorageRoot: root, HMACSecret: secret, MaxObjectBytes: 8, MaxChunkBytes: 4, MaxParts: 2}
	server, err := NewServer(cfg, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	token := mustToken(t, secret, TokenClaims{Action: "upload", ExpiresAt: time.Now().Add(time.Hour).Unix(), TokenID: "one-capability", MaxBytes: 8})
	body := `{"filename":"same.bin","content_type":"application/octet-stream","size":4}`
	first := request(t, server.Handler(), http.MethodPost, "/v1/uploads", body, token, nil)
	second := request(t, server.Handler(), http.MethodPost, "/v1/uploads", body, token, nil)
	if first.Code != http.StatusCreated || second.Code != http.StatusCreated {
		t.Fatalf("statuses: first=%d second=%d", first.Code, second.Code)
	}
	var initial, repeated initiateResponse
	decodeResponse(t, first, &initial)
	decodeResponse(t, second, &repeated)
	if initial != repeated {
		t.Fatalf("repeat created another session: %#v != %#v", initial, repeated)
	}

	restarted, err := NewServer(cfg, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	afterRestart := request(t, restarted.Handler(), http.MethodPost, "/v1/uploads", body, token, nil)
	var persisted initiateResponse
	decodeResponse(t, afterRestart, &persisted)
	if afterRestart.Code != http.StatusCreated || persisted != initial {
		t.Fatalf("restart lost idempotency: %d %#v", afterRestart.Code, persisted)
	}

	changed := request(t, restarted.Handler(), http.MethodPost, "/v1/uploads", `{"filename":"other.bin","size":4}`, token, nil)
	if changed.Code != http.StatusConflict {
		t.Fatalf("same jti with changed request returned %d: %s", changed.Code, changed.Body.String())
	}
}

func TestLimitsAndIncompleteUpload(t *testing.T) {
	secret := []byte(strings.Repeat("l", 32))
	cfg := Config{StorageRoot: t.TempDir(), HMACSecret: secret, MaxObjectBytes: 8, MaxChunkBytes: 4, MaxParts: 2}
	server, err := NewServer(cfg, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	token := mustToken(t, secret, TokenClaims{Action: "upload", ExpiresAt: time.Now().Add(time.Hour).Unix(), TokenID: "limits", MaxBytes: 8})
	tooLarge := request(t, handler, http.MethodPost, "/v1/uploads", `{"filename":"large","size":9}`, token, nil)
	if tooLarge.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("large initiate: %d %s", tooLarge.Code, tooLarge.Body.String())
	}
	created := request(t, handler, http.MethodPost, "/v1/uploads", `{"filename":"small","size":4}`, token, nil)
	var upload initiateResponse
	decodeResponse(t, created, &upload)
	oversizedPart := request(t, handler, http.MethodPut, "/v1/uploads/"+upload.UploadID+"/parts/1", "12345", token, nil)
	if oversizedPart.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("large part: %d %s", oversizedPart.Code, oversizedPart.Body.String())
	}
	incomplete := request(t, handler, http.MethodPost, "/v1/uploads/"+upload.UploadID+"/complete", "", token, nil)
	if incomplete.Code != http.StatusConflict {
		t.Fatalf("incomplete upload: %d %s", incomplete.Code, incomplete.Body.String())
	}
}

func TestHealthz(t *testing.T) {
	secret := []byte(strings.Repeat("h", 32))
	server, err := NewServer(Config{StorageRoot: t.TempDir(), HMACSecret: secret, MaxObjectBytes: 8, MaxChunkBytes: 4, MaxParts: 2}, nil)
	if err != nil {
		t.Fatal(err)
	}
	response := request(t, server.Handler(), http.MethodGet, "/healthz", "", "", nil)
	if response.Code != http.StatusOK || response.Body.String() != "{\"status\":\"ok\"}\n" {
		t.Fatalf("healthz: %d %s", response.Code, response.Body.String())
	}
}

func request(t *testing.T, handler http.Handler, method, target, body, token string, headers map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, target, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	for name, value := range headers {
		req.Header.Set(name, value)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)
	return response
}

func mustToken(t *testing.T, secret []byte, claims TokenClaims) string {
	t.Helper()
	token, err := SignToken(secret, claims)
	if err != nil {
		t.Fatal(err)
	}
	return token
}

func decodeResponse(t *testing.T, response *httptest.ResponseRecorder, destination any) {
	t.Helper()
	if err := json.Unmarshal(response.Body.Bytes(), destination); err != nil {
		t.Fatalf("decode response %d %s: %v", response.Code, response.Body.String(), err)
	}
}
