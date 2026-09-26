package gateway

import (
	"strings"
	"testing"
	"time"
)

func TestConfigCleanupDurations(t *testing.T) {
	t.Setenv("HMAC_SECRET", strings.Repeat("s", 32))
	t.Setenv("UPLOAD_TTL", "90m")
	t.Setenv("CLEANUP_PERIOD", "45s")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.UploadTTL != 90*time.Minute || cfg.CleanupPeriod != 45*time.Second {
		t.Fatalf("unexpected cleanup config: ttl=%s period=%s", cfg.UploadTTL, cfg.CleanupPeriod)
	}
}

func TestConfigRejectsInvalidCleanupDuration(t *testing.T) {
	t.Setenv("HMAC_SECRET", strings.Repeat("s", 32))
	t.Setenv("UPLOAD_TTL", "0s")
	if _, err := ConfigFromEnv(); err == nil {
		t.Fatal("expected invalid UPLOAD_TTL error")
	}
}
