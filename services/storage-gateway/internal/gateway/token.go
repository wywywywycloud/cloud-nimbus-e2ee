package gateway

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"
)

const tokenVersion = 1

type TokenClaims struct {
	Version   int    `json:"v"`
	Action    string `json:"action"`
	ExpiresAt int64  `json:"exp"`
	TokenID   string `json:"jti"`
	ObjectKey string `json:"object_key,omitempty"`
	MaxBytes  int64  `json:"max_bytes,omitempty"`
}

func SignToken(secret []byte, claims TokenClaims) (string, error) {
	if len(secret) < 32 {
		return "", errors.New("signing secret must contain at least 32 bytes")
	}
	if claims.Version == 0 {
		claims.Version = tokenVersion
	}
	if err := validateClaims(claims); err != nil {
		return "", err
	}
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", fmt.Errorf("marshal claims: %w", err)
	}
	encoded := base64.RawURLEncoding.EncodeToString(payload)
	signature := tokenMAC(secret, encoded)
	return encoded + "." + base64.RawURLEncoding.EncodeToString(signature), nil
}

func VerifyToken(secret []byte, raw string, now time.Time, clockSkew time.Duration) (TokenClaims, error) {
	var claims TokenClaims
	parts := strings.Split(raw, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return claims, errors.New("malformed token")
	}
	provided, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil || !hmac.Equal(provided, tokenMAC(secret, parts[0])) {
		return claims, errors.New("invalid token signature")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return claims, errors.New("invalid token payload")
	}
	decoder := json.NewDecoder(strings.NewReader(string(payload)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&claims); err != nil {
		return TokenClaims{}, errors.New("invalid token claims")
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return TokenClaims{}, errors.New("invalid token claims")
	}
	if err := validateClaims(claims); err != nil {
		return TokenClaims{}, err
	}
	if now.Add(-clockSkew).Unix() >= claims.ExpiresAt {
		return TokenClaims{}, errors.New("token expired")
	}
	return claims, nil
}

func validateClaims(claims TokenClaims) error {
	if claims.Version != tokenVersion {
		return errors.New("unsupported token version")
	}
	if claims.Action != "upload" && claims.Action != "download" {
		return errors.New("invalid token action")
	}
	if claims.ExpiresAt <= 0 || claims.TokenID == "" || len(claims.TokenID) > 128 {
		return errors.New("invalid token identity or expiry")
	}
	if claims.Action == "download" && !validObjectKey(claims.ObjectKey) {
		return errors.New("download token requires a valid object key")
	}
	if claims.MaxBytes < 0 {
		return errors.New("max_bytes cannot be negative")
	}
	return nil
}

func tokenMAC(secret []byte, payload string) []byte {
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(payload))
	return mac.Sum(nil)
}
