package cloudfrontcookie

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"strings"
	"testing"
	"time"
)

func TestCookiesForChapter(t *testing.T) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	pemKey := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	s, err := New(string(pemKey), "KTEST", "https://img.example.com/images", ".example.com", 5*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	cookies, err := s.CookiesForChapter("series-a", "ch-1", time.Unix(1000, 0))
	if err != nil {
		t.Fatal(err)
	}
	if len(cookies) != 4 {
		t.Fatalf("cookies=%d", len(cookies))
	}
	foundPolicy := false
	for _, c := range cookies {
		if !c.Secure || !c.HttpOnly || c.Domain != ".example.com" {
			t.Fatalf("unsafe cookie: %+v", c)
		}
		if c.Name == "CloudFront-Policy" {
			foundPolicy = strings.TrimSpace(c.Value) != ""
		}
	}
	if !foundPolicy {
		t.Fatal("policy cookie missing")
	}
}

func TestClearCookies(t *testing.T) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	signer, err := New(string(pemBytes), "KTEST", "https://img.example.com/images", ".example.com", time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	cookies := signer.ClearCookies()
	if len(cookies) != 4 {
		t.Fatalf("expected 4 clear cookies, got %d", len(cookies))
	}
	for _, c := range cookies {
		if c.MaxAge != -1 || !c.HttpOnly || !c.Secure || c.Domain != ".example.com" {
			t.Fatalf("unsafe clear cookie: %#v", c)
		}
	}
}
