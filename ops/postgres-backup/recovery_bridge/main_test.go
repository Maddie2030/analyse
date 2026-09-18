package main

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type fakeArtifactSource struct {
	artifact *stagedArtifact
	err      error
	seenID   string
}

func (f *fakeArtifactSource) Open(_ context.Context, publicID string) (*stagedArtifact, error) {
	f.seenID = publicID
	if f.err != nil {
		return nil, f.err
	}
	return f.artifact, nil
}

func TestBridgeHealthRequiresCredentialAndDoesNotTouchRecoveryStore(t *testing.T) {
	source := &fakeArtifactSource{}
	handler := bridgeHandler("secret-token", source)

	unauthorized := httptest.NewRequest(http.MethodGet, "/internal/v1/recovery/health", nil)
	unauthorizedResponse := httptest.NewRecorder()
	handler.ServeHTTP(unauthorizedResponse, unauthorized)
	if unauthorizedResponse.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized health status = %d, want 401", unauthorizedResponse.Code)
	}

	req := httptest.NewRequest(http.MethodGet, "/internal/v1/recovery/health", nil)
	req.Header.Set("X-MReader-Internal-Token", "secret-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)
	if response.Code != http.StatusOK {
		t.Fatalf("authorized health status = %d, want 200", response.Code)
	}
	if source.seenID != "" {
		t.Fatalf("health endpoint touched recovery store: %q", source.seenID)
	}
}

func TestBridgeRejectsMissingOrWrongCredential(t *testing.T) {
	source := &fakeArtifactSource{}
	handler := bridgeHandler("secret-token", source)
	for _, token := range []string{"", "wrong-token"} {
		req := httptest.NewRequest(http.MethodGet, "/internal/v1/recovery/download/bkp_0123456789abcdef01234567", nil)
		if token != "" {
			req.Header.Set("X-MReader-Internal-Token", token)
		}
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		if response.Code != http.StatusUnauthorized {
			t.Fatalf("token %q: got status %d, want 401", token, response.Code)
		}
	}
	if source.seenID != "" {
		t.Fatalf("unauthorized request reached recovery source: %q", source.seenID)
	}
}

func TestBridgeValidatesOpaquePublicIdentifierBeforeLookup(t *testing.T) {
	source := &fakeArtifactSource{}
	handler := bridgeHandler("secret-token", source)
	req := httptest.NewRequest(http.MethodGet, "/internal/v1/recovery/download/../../private.dump", nil)
	req.Header.Set("X-MReader-Internal-Token", "secret-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("got status %d, want 400", response.Code)
	}
	if source.seenID != "" {
		t.Fatalf("invalid public id reached recovery source: %q", source.seenID)
	}
}

func TestBridgeMapsMissingRecoveryPointWithoutLeakingStorageDetails(t *testing.T) {
	source := &fakeArtifactSource{err: errRecoveryNotFound}
	handler := bridgeHandler("secret-token", source)
	req := httptest.NewRequest(http.MethodGet, "/internal/v1/recovery/download/bkp_0123456789abcdef01234567", nil)
	req.Header.Set("X-MReader-Internal-Token", "secret-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)
	if response.Code != http.StatusNotFound {
		t.Fatalf("got status %d, want 404", response.Code)
	}
	body := response.Body.String()
	if strings.Contains(body, "/mreader-db-protection") || strings.Contains(body, "database.dump") {
		t.Fatalf("response leaked storage details: %q", body)
	}
}

func TestBridgeStreamsVerifiedArtifactUsingOnlyPublicFilename(t *testing.T) {
	cleaned := false
	source := &fakeArtifactSource{artifact: &stagedArtifact{
		Reader:    io.NopCloser(strings.NewReader("verified-backup")),
		Size:      15,
		SHA256:    strings.Repeat("a", 64),
		Extension: ".dump",
		Cleanup:   func() { cleaned = true },
	}}
	handler := bridgeHandler("secret-token", source)
	publicID := "bkp_0123456789abcdef01234567"
	req := httptest.NewRequest(http.MethodGet, "/internal/v1/recovery/download/"+publicID, nil)
	req.Header.Set("X-MReader-Internal-Token", "secret-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)
	if response.Code != http.StatusOK {
		t.Fatalf("got status %d, want 200: %s", response.Code, response.Body.String())
	}
	if got := response.Body.String(); got != "verified-backup" {
		t.Fatalf("unexpected body %q", got)
	}
	disposition := response.Header().Get("Content-Disposition")
	if !strings.Contains(disposition, publicID+".dump") {
		t.Fatalf("public filename missing from content disposition: %q", disposition)
	}
	if strings.Contains(disposition, "internal") || strings.Contains(disposition, "/") {
		t.Fatalf("content disposition leaked an internal name/path: %q", disposition)
	}
	if response.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("download must be non-cacheable")
	}
	if response.Header().Get("X-MReader-Content-SHA256") != strings.Repeat("a", 64) {
		t.Fatalf("verified checksum header missing")
	}
	if !cleaned {
		t.Fatalf("staged download was not cleaned")
	}
}

func TestLocalArtifactSourceRejectsSymlinkedRecoveryRoot(t *testing.T) {
	realRoot := t.TempDir()
	linkParent := t.TempDir()
	root := filepath.Join(linkParent, "recovery-root")
	if err := os.Symlink(realRoot, root); err != nil {
		t.Fatalf("create recovery root symlink: %v", err)
	}
	store := filepath.Join(t.TempDir(), "fake-store.sh")
	if err := os.WriteFile(store, []byte("#!/bin/sh\nexit 0\n"), 0o700); err != nil {
		t.Fatalf("write fake store: %v", err)
	}
	_, err := (localArtifactSource{Root: root, Store: store}).Open(context.Background(), "bkp_0123456789abcdef01234567")
	if err == nil || !strings.Contains(err.Error(), "symlink") {
		t.Fatalf("expected recovery root symlink rejection, got %v", err)
	}
}

func TestLocalArtifactSourceRejectsSymlinkedStagingBeforeCreatingDownloadFiles(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(root, "staging")); err != nil {
		t.Fatalf("create staging symlink: %v", err)
	}

	store := filepath.Join(t.TempDir(), "fake-store.sh")
	publicID := "bkp_0123456789abcdef01234567"
	script := `#!/bin/sh
if [ "$1" = catalog ]; then
  printf '%s\n' '{"recovery_points":[{"recovery_id":"internal-id","public_id":"` + publicID + `","kind":"logical_dump","sha256":"` + strings.Repeat("a", 64) + `","verified":true,"size_bytes":7}]}'
  exit 0
fi
if [ "$1" = copy-artifact ]; then
  printf payload > "$4"
  exit 0
fi
exit 2
`
	if err := os.WriteFile(store, []byte(script), 0o700); err != nil {
		t.Fatalf("write fake store: %v", err)
	}

	_, err := (localArtifactSource{Root: root, Store: store}).Open(context.Background(), publicID)
	if err == nil {
		t.Fatalf("expected symlinked staging to be rejected")
	}
	entries, readErr := os.ReadDir(outside)
	if readErr != nil {
		t.Fatalf("read outside staging target: %v", readErr)
	}
	if len(entries) != 0 {
		t.Fatalf("bridge created files through staging symlink: %v", entries)
	}
}

func TestBridgeMapsInternalSourceFailureToServiceUnavailable(t *testing.T) {
	source := &fakeArtifactSource{err: errors.New("/private/root exploded")}
	handler := bridgeHandler("secret-token", source)
	req := httptest.NewRequest(http.MethodGet, "/internal/v1/recovery/download/bkp_0123456789abcdef01234567", nil)
	req.Header.Set("X-MReader-Internal-Token", "secret-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, req)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("got status %d, want 503", response.Code)
	}
	if strings.Contains(response.Body.String(), "/private/root") {
		t.Fatalf("internal error leaked to caller: %q", response.Body.String())
	}
}

func TestCheckBridgeHealthAuthenticatesAndRequiresOK(t *testing.T) {
	const token = "secret-token"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/recovery/health" {
			http.NotFound(w, r)
			return
		}
		if r.Header.Get(internalTokenHeader) != token {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	if err := checkBridgeHealth(context.Background(), server.Client(), token, server.URL); err != nil {
		t.Fatalf("authorized healthcheck failed: %v", err)
	}
	if err := checkBridgeHealth(context.Background(), server.Client(), "wrong", server.URL); err == nil {
		t.Fatal("wrong-token healthcheck unexpectedly succeeded")
	}
}
