package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const internalTokenHeader = "X-MReader-Internal-Token"
const downloadPrefix = "/internal/v1/recovery/download/"

var publicRecoveryID = regexp.MustCompile(`^bkp_[0-9a-f]{24}$`)
var errRecoveryNotFound = errors.New("recovery point not found")

type stagedArtifact struct {
	Reader    io.ReadCloser
	Size      int64
	SHA256    string
	Extension string
	Cleanup   func()
}

type artifactSource interface {
	Open(context.Context, string) (*stagedArtifact, error)
}

type catalogDocument struct {
	RecoveryPoints []catalogRecoveryPoint `json:"recovery_points"`
}

type catalogRecoveryPoint struct {
	RecoveryID string `json:"recovery_id"`
	PublicID   string `json:"public_id"`
	Kind       string `json:"kind"`
	SHA256     string `json:"sha256"`
	Verified   bool   `json:"verified"`
	SizeBytes  int64  `json:"size_bytes"`
}

type localArtifactSource struct {
	Root  string
	Store string
}

func validateRecoveryRoot(root string) error {
	rootInfo, err := os.Lstat(root)
	if err != nil {
		return fmt.Errorf("inspect recovery root: %w", err)
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("recovery root must not be a symlink")
	}
	if !rootInfo.IsDir() {
		return fmt.Errorf("recovery root must be a directory")
	}
	return nil
}

func (s localArtifactSource) selectRecoveryPoint(ctx context.Context, publicID string) (*catalogRecoveryPoint, error) {
	catalogRaw, err := exec.CommandContext(ctx, s.Store, "catalog", s.Root).Output()
	if err != nil {
		return nil, fmt.Errorf("catalog verified recovery points: %w", err)
	}
	var catalog catalogDocument
	if err := json.Unmarshal(catalogRaw, &catalog); err != nil {
		return nil, fmt.Errorf("decode verified recovery catalog: %w", err)
	}
	var selected *catalogRecoveryPoint
	for i := range catalog.RecoveryPoints {
		item := &catalog.RecoveryPoints[i]
		if item.PublicID != publicID || !item.Verified {
			continue
		}
		if selected != nil {
			return nil, fmt.Errorf("public recovery identifier is not unique")
		}
		selected = item
	}
	if selected == nil {
		return nil, errRecoveryNotFound
	}
	return selected, nil
}

func prepareRecoveryStaging(root string) (string, error) {
	stagingRoot := filepath.Join(root, "staging")
	if info, err := os.Lstat(stagingRoot); err == nil {
		if info.Mode()&os.ModeSymlink != 0 {
			return "", fmt.Errorf("recovery staging must not be a symlink")
		}
		if !info.IsDir() {
			return "", fmt.Errorf("recovery staging must be a directory")
		}
	} else if !os.IsNotExist(err) {
		return "", fmt.Errorf("inspect recovery staging: %w", err)
	}
	if err := os.MkdirAll(stagingRoot, 0o700); err != nil {
		return "", fmt.Errorf("prepare recovery staging: %w", err)
	}
	stageInfo, err := os.Lstat(stagingRoot)
	if err != nil {
		return "", fmt.Errorf("inspect prepared recovery staging: %w", err)
	}
	if stageInfo.Mode()&os.ModeSymlink != 0 || !stageInfo.IsDir() {
		return "", fmt.Errorf("recovery staging must be a real directory")
	}
	return stagingRoot, nil
}

func (s localArtifactSource) stageRecoveryArtifact(ctx context.Context, publicID string, selected *catalogRecoveryPoint, stagingRoot string) (*stagedArtifact, error) {
	stageDir, err := os.MkdirTemp(stagingRoot, ".download-"+publicID+"-")
	if err != nil {
		return nil, fmt.Errorf("create recovery download staging: %w", err)
	}
	cleanupDir := true
	defer func() {
		if cleanupDir {
			_ = os.RemoveAll(stageDir)
		}
	}()

	destination := filepath.Join(stageDir, "artifact")
	if output, err := exec.CommandContext(ctx, s.Store, "copy-artifact", s.Root, selected.RecoveryID, destination).CombinedOutput(); err != nil {
		return nil, fmt.Errorf("stage verified recovery artifact: %w (%s)", err, strings.TrimSpace(string(output)))
	}
	file, err := os.Open(destination)
	if err != nil {
		return nil, fmt.Errorf("open staged recovery artifact: %w", err)
	}
	stat, err := file.Stat()
	if err != nil {
		_ = file.Close()
		return nil, fmt.Errorf("stat staged recovery artifact: %w", err)
	}
	if selected.SizeBytes > 0 && stat.Size() != selected.SizeBytes {
		_ = file.Close()
		return nil, fmt.Errorf("staged recovery artifact size mismatch")
	}

	extension := ".dump"
	if selected.Kind == "physical_snapshot" {
		extension = ".tar"
	}
	cleanupDir = false
	return &stagedArtifact{
		Reader:    file,
		Size:      stat.Size(),
		SHA256:    selected.SHA256,
		Extension: extension,
		Cleanup: func() {
			_ = file.Close()
			_ = os.RemoveAll(stageDir)
		},
	}, nil
}

func (s localArtifactSource) Open(ctx context.Context, publicID string) (*stagedArtifact, error) {
	if err := validateRecoveryRoot(s.Root); err != nil {
		return nil, err
	}
	selected, err := s.selectRecoveryPoint(ctx, publicID)
	if err != nil {
		return nil, err
	}
	stagingRoot, err := prepareRecoveryStaging(s.Root)
	if err != nil {
		return nil, err
	}
	return s.stageRecoveryArtifact(ctx, publicID, selected, stagingRoot)
}

func authorized(expected, supplied string) bool {
	if expected == "" || len(expected) != len(supplied) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(expected), []byte(supplied)) == 1
}

func checkBridgeHealth(ctx context.Context, client *http.Client, token, baseURL string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/internal/v1/recovery/health", nil)
	if err != nil {
		return fmt.Errorf("build recovery bridge health request: %w", err)
	}
	req.Header.Set(internalTokenHeader, token)
	response, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("request recovery bridge health: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("recovery bridge health returned %s", response.Status)
	}
	return nil
}

func bridgeHandler(token string, source artifactSource) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.Header().Set("Allow", http.MethodGet)
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !authorized(token, r.Header.Get(internalTokenHeader)) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if r.URL.Path == "/internal/v1/recovery/health" {
			w.Header().Set("Cache-Control", "no-store")
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			_, _ = io.WriteString(w, `{"status":"ok"}`)
			return
		}
		if !strings.HasPrefix(r.URL.Path, downloadPrefix) {
			http.NotFound(w, r)
			return
		}
		publicID := strings.TrimPrefix(r.URL.Path, downloadPrefix)
		if !publicRecoveryID.MatchString(publicID) {
			http.Error(w, "invalid recovery identifier", http.StatusBadRequest)
			return
		}

		artifact, err := source.Open(r.Context(), publicID)
		if err != nil {
			if errors.Is(err, errRecoveryNotFound) {
				http.Error(w, "recovery point not found", http.StatusNotFound)
				return
			}
			log.Printf("recovery bridge staging failed for %s: %v", publicID, err)
			http.Error(w, "recovery bridge unavailable", http.StatusServiceUnavailable)
			return
		}
		if artifact == nil || artifact.Reader == nil || artifact.Cleanup == nil {
			log.Printf("recovery bridge source returned an invalid staged artifact for %s", publicID)
			http.Error(w, "recovery bridge unavailable", http.StatusServiceUnavailable)
			return
		}
		defer artifact.Cleanup()

		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s%s"`, publicID, artifact.Extension))
		w.Header().Set("X-Content-Type-Options", "nosniff")
		if artifact.SHA256 != "" {
			w.Header().Set("X-MReader-Content-SHA256", artifact.SHA256)
		}
		if artifact.Size >= 0 {
			w.Header().Set("Content-Length", strconv.FormatInt(artifact.Size, 10))
		}
		w.WriteHeader(http.StatusOK)
		if _, err := io.Copy(w, artifact.Reader); err != nil {
			log.Printf("recovery bridge stream interrupted for %s: %v", publicID, err)
		}
	})
}

func main() {
	token := strings.TrimSpace(os.Getenv("RECOVERY_BRIDGE_TOKEN"))
	if token == "" {
		log.Fatal("RECOVERY_BRIDGE_TOKEN is required")
	}
	if len(os.Args) == 2 && os.Args[1] == "healthcheck" {
		baseURL := strings.TrimSpace(os.Getenv("RECOVERY_BRIDGE_LOCAL_URL"))
		if baseURL == "" {
			baseURL = "http://127.0.0.1:8082"
		}
		client := &http.Client{Timeout: 3 * time.Second}
		if err := checkBridgeHealth(context.Background(), client, token, baseURL); err != nil {
			log.Fatal(err)
		}
		return
	}
	root := strings.TrimSpace(os.Getenv("POSTGRES_BACKUP_LOCAL_ROOT"))
	if root == "" {
		root = "/mreader-db-protection"
	}
	store := strings.TrimSpace(os.Getenv("MREADER_LOCAL_RECOVERY_STORE"))
	if store == "" {
		store = "/usr/local/bin/mreader-local-recovery-store"
	}
	listen := strings.TrimSpace(os.Getenv("RECOVERY_BRIDGE_LISTEN_ADDR"))
	if listen == "" {
		listen = "0.0.0.0:8082"
	}

	server := &http.Server{
		Addr:              listen,
		Handler:           bridgeHandler(token, localArtifactSource{Root: root, Store: store}),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    16 * 1024,
	}
	log.Printf("private recovery bridge listening on %s", listen)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
