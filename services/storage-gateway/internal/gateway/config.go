package gateway

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"time"
)

const (
	defaultMaxObjectBytes = int64(50 * 1024 * 1024)
	defaultMaxChunkBytes  = int64(8 * 1024 * 1024)
	defaultMaxParts       = 10_000
	defaultUploadTTL      = 24 * time.Hour
	defaultCleanupPeriod  = 15 * time.Minute
)

type Config struct {
	Address        string
	StorageRoot    string
	HMACSecret     []byte
	MaxObjectBytes int64
	MaxChunkBytes  int64
	MaxParts       int
	TokenClockSkew time.Duration
	UploadTTL      time.Duration
	CleanupPeriod  time.Duration
}

func ConfigFromEnv() (Config, error) {
	cfg := Config{
		Address:        envOr("ADDRESS", ":8080"),
		StorageRoot:    envOr("STORAGE_ROOT", "/data"),
		HMACSecret:     []byte(os.Getenv("HMAC_SECRET")),
		MaxObjectBytes: defaultMaxObjectBytes,
		MaxChunkBytes:  defaultMaxChunkBytes,
		MaxParts:       defaultMaxParts,
		TokenClockSkew: 15 * time.Second,
		UploadTTL:      defaultUploadTTL,
		CleanupPeriod:  defaultCleanupPeriod,
	}
	var err error
	if cfg.MaxObjectBytes, err = positiveInt64Env("MAX_OBJECT_BYTES", cfg.MaxObjectBytes); err != nil {
		return Config{}, err
	}
	if cfg.MaxChunkBytes, err = positiveInt64Env("MAX_CHUNK_BYTES", cfg.MaxChunkBytes); err != nil {
		return Config{}, err
	}
	parts, err := positiveInt64Env("MAX_PARTS", int64(cfg.MaxParts))
	if err != nil {
		return Config{}, err
	}
	if parts > int64(^uint(0)>>1) {
		return Config{}, errors.New("MAX_PARTS is too large")
	}
	cfg.MaxParts = int(parts)
	if cfg.UploadTTL, err = positiveDurationEnv("UPLOAD_TTL", cfg.UploadTTL); err != nil {
		return Config{}, err
	}
	if cfg.CleanupPeriod, err = positiveDurationEnv("CLEANUP_PERIOD", cfg.CleanupPeriod); err != nil {
		return Config{}, err
	}
	if len(cfg.HMACSecret) < 32 {
		return Config{}, errors.New("HMAC_SECRET must contain at least 32 bytes")
	}
	if cfg.MaxChunkBytes > cfg.MaxObjectBytes {
		return Config{}, errors.New("MAX_CHUNK_BYTES cannot exceed MAX_OBJECT_BYTES")
	}
	return cfg, nil
}

func (cfg Config) withDefaults() Config {
	if cfg.UploadTTL <= 0 {
		cfg.UploadTTL = defaultUploadTTL
	}
	if cfg.CleanupPeriod <= 0 {
		cfg.CleanupPeriod = defaultCleanupPeriod
	}
	return cfg
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func positiveInt64Env(name string, fallback int64) (int64, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || value <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer", name)
	}
	return value, nil
}

func positiveDurationEnv(name string, fallback time.Duration) (time.Duration, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback, nil
	}
	value, err := time.ParseDuration(raw)
	if err != nil || value <= 0 {
		return 0, fmt.Errorf("%s must be a positive Go duration", name)
	}
	return value, nil
}
