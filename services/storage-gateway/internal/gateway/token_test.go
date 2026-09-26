package gateway

import (
	"strings"
	"testing"
	"time"
)

func TestTokenRoundTripAndTamperDetection(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Unix(1_800_000_000, 0)
	original := TokenClaims{Action: "upload", ExpiresAt: now.Add(time.Minute).Unix(), TokenID: "upload-grant-1", MaxBytes: 1024}
	token, err := SignToken(secret, original)
	if err != nil {
		t.Fatal(err)
	}
	claims, err := VerifyToken(secret, token, now, 0)
	if err != nil {
		t.Fatal(err)
	}
	if claims.Action != original.Action || claims.TokenID != original.TokenID || claims.MaxBytes != original.MaxBytes {
		t.Fatalf("unexpected claims: %#v", claims)
	}
	tampered := token[:len(token)-1] + "A"
	if _, err := VerifyToken(secret, tampered, now, 0); err == nil {
		t.Fatal("tampered token was accepted")
	}
}

func TestTokenExpiryAndDownloadScope(t *testing.T) {
	secret := []byte(strings.Repeat("x", 32))
	now := time.Unix(1_800_000_000, 0)
	expired, err := SignToken(secret, TokenClaims{Action: "upload", ExpiresAt: now.Add(-time.Second).Unix(), TokenID: "expired"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := VerifyToken(secret, expired, now, 0); err == nil {
		t.Fatal("expired token was accepted")
	}
	if _, err := SignToken(secret, TokenClaims{Action: "download", ExpiresAt: now.Add(time.Minute).Unix(), TokenID: "download"}); err == nil {
		t.Fatal("download token without object key was signed")
	}
}
