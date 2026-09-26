# cloud.nimbus storage gateway

Minimal Go data plane for large/resumable file transfers. It is intentionally isolated from Django: a future control plane signs short-lived upload/download capabilities and stores only the opaque object key returned by this service.

The current backend is a single-node local filesystem. Its API and storage boundary are designed so the implementation can later be replaced with an S3-compatible multipart backend without changing browser-facing semantics.

## Security and durability model

- Every upload operation requires an HMAC-signed `upload` token. A `jti` durably identifies exactly one upload session: identical initiate retries return that session, while changed initiate parameters are rejected. A different valid token cannot inspect, add parts to, complete, or abort it.
- Downloads require a short-lived `download` token scoped to the exact random object key. Tokens are accepted as `Authorization: Bearer …`; downloads additionally accept `?token=…` for normal browser navigation.
- Object keys use 256 bits from `crypto/rand`. Client filenames never become storage paths.
- Parts and object assembly use bounded `io.Copy` streams. Request bodies and completed objects are never loaded fully into memory.
- Metadata and completed object publication use temporary files, `fsync`, and atomic rename on the same filesystem.
- Active uploads are removed after a configurable inactivity TTL or capability expiry. Cleanup first persists a grant tombstone, then removes parts and upload metadata, so a still-valid retried capability cannot recreate a second session.
- Single byte ranges are supported; multipart ranges are rejected with `416`.
- Files are returned as attachments with `application/octet-stream`, `nosniff`, `no-store`, and `no-referrer`.
- The image runs as UID/GID `65532` from `scratch`. Mount `/data` with ownership that lets this identity write.

The local backend is for one service replica attached to one persistent volume. The in-process striped locks do not coordinate multiple replicas. A multi-replica deployment must first replace it with an object-store multipart backend and distributed metadata/locking.

## Configuration

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `HMAC_SECRET` | yes | — | At least 32 bytes; shared only with the token-issuing control plane |
| `ADDRESS` | no | `:8080` | HTTP listen address |
| `STORAGE_ROOT` | no | `/data` | Persistent local filesystem root |
| `MAX_OBJECT_BYTES` | no | `52428800` | Maximum declared object size |
| `MAX_CHUNK_BYTES` | no | `8388608` | Maximum part size and advertised chunk size |
| `MAX_PARTS` | no | `10000` | Maximum part number/count |
| `UPLOAD_TTL` | no | `24h` | Inactivity TTL for unfinished uploads (Go duration) |
| `CLEANUP_PERIOD` | no | `15m` | Interval between cleanup passes (Go duration) |

The service refuses to start when the secret is weak or limits are inconsistent.

## Capability token format

Tokens are dependency-free compact capabilities:

```text
base64url(raw JSON payload) + "." + base64url(HMAC-SHA256(secret, encoded payload))
```

No base64 padding is used. The JSON schema is:

```json
{
  "v": 1,
  "action": "upload",
  "exp": 1800000000,
  "jti": "unique-control-plane-grant-id",
  "max_bytes": 52428800
}
```

For a download token, set `action` to `download` and include the exact `object_key`; `max_bytes` is omitted. `exp` is a Unix timestamp. Use unique `jti` values, rotate the shared secret operationally, keep token TTLs short, and never log query strings or `Authorization` headers at the edge.

## API

All errors are JSON: `{"error":{"code":"…","message":"…"}}`.

### Health

```http
GET /healthz
```

### Initiate

```http
POST /v1/uploads
Authorization: Bearer <upload-token>
Content-Type: application/json

{"filename":"report.pdf","content_type":"application/pdf","size":7340032}
```

Returns `upload_id`, random `object_key`, `chunk_size`, and `max_parts`. An identical retry with the same token `jti` returns `201` with the same values. Reusing the `jti` with different filename, media type, or size returns `409`.

### Upload or replace a part

```http
PUT /v1/uploads/{upload_id}/parts/{part_number}
Authorization: Bearer <same-upload-token>
Content-Length: ...

<raw bytes>
```

Part numbers begin at 1. Re-uploading a part atomically replaces it. At completion, all parts must be contiguous; every non-final part must equal `chunk_size`, and the total must equal the size declared at initiation.

### Status

```http
GET /v1/uploads/{upload_id}
Authorization: Bearer <same-upload-token>
```

Returns state, received bytes, and sorted part metadata including SHA-256.

### Complete

```http
POST /v1/uploads/{upload_id}/complete
Authorization: Bearer <same-upload-token>
```

Completion is idempotent and returns persisted object metadata.

### Abort

```http
DELETE /v1/uploads/{upload_id}
Authorization: Bearer <same-upload-token>
```

Abort is idempotent until completion and removes part bodies while preserving the small terminal metadata record.

### Download

```http
GET /v1/objects/{object_key}?token=<download-token>
Range: bytes=1048576-2097151
```

`HEAD` is also supported. A valid single range returns `206`; an invalid or multipart range returns `416`.

## Development

The module has no third-party dependencies:

```bash
go test ./...
go run ./cmd/storage-gateway
```

Example container build and run:

```bash
docker build -t cloud-nimbus-storage-gateway .
docker run --rm -p 8080:8080 \
  -e HMAC_SECRET='replace-with-at-least-32-random-bytes' \
  -v cloud-nimbus-data:/data \
  cloud-nimbus-storage-gateway
```

For production, terminate TLS at a trusted reverse proxy, disable request/query logging on capability routes, enforce a matching body-size limit at the proxy, and monitor persistent-volume capacity.
