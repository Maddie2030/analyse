package model

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

const MaxPublicationPages = 4096
const maxPublicationInteger int64 = 9007199254740991

var ErrInvalidPublicationCommand = errors.New("invalid publication command")
var ErrPublicationPayloadDigest = errors.New("publication payload digest mismatch")

func isLowerHex(value string, size int) bool {
	if len(value) != size {
		return false
	}
	for _, ch := range value {
		if !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')) {
			return false
		}
	}
	return true
}

func validUUID(value string) bool {
	if len(value) != 36 || value[8] != '-' || value[13] != '-' || value[18] != '-' || value[23] != '-' {
		return false
	}
	for i, ch := range value {
		if i == 8 || i == 13 || i == 18 || i == 23 {
			continue
		}
		if !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')) {
			return false
		}
	}
	if value[14] < '1' || value[14] > '5' {
		return false
	}
	if !strings.ContainsRune("89ab", rune(value[19])) {
		return false
	}
	return true
}

func validSlug(value string) bool {
	if value == "" || len(value) > 255 || value[0] == '-' || value[len(value)-1] == '-' {
		return false
	}
	previousDash := false
	for _, ch := range value {
		if ch == '-' {
			if previousDash {
				return false
			}
			previousDash = true
			continue
		}
		previousDash = false
		if !((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')) {
			return false
		}
	}
	return true
}

func validChapterNumber(value string) bool {
	parts := strings.Split(value, ".")
	if len(parts) != 2 || len(parts[1]) != 2 || len(parts[0]) == 0 || len(parts[0]) > 6 {
		return false
	}
	if len(parts[0]) > 1 && parts[0][0] == '0' {
		return false
	}
	for _, part := range parts {
		for _, ch := range part {
			if ch < '0' || ch > '9' {
				return false
			}
		}
	}
	return true
}

func validTitle(value *string) bool {
	if value == nil {
		return true
	}
	if !utf8.ValidString(*value) || len([]rune(*value)) > 255 {
		return false
	}
	for _, ch := range *value {
		if ch < 32 || ch == 127 || (ch >= 0xD800 && ch <= 0xDFFF) {
			return false
		}
	}
	return true
}

func assetVersionV4(seed string) string {
	sum := sha256.Sum256([]byte("mreader-v4-overlap-tilepack:" + seed))
	return hex.EncodeToString(sum[:])[:20]
}

func validatePublicationAsset(asset PublicationAsset, expectedPath string, rows, columns int) bool {
	return asset.ImagePath == expectedPath && len(asset.ImagePath) <= 500 &&
		asset.Width >= columns && asset.Width <= 20000 &&
		asset.Height >= rows && asset.Height <= 40000 &&
		asset.SizeBytes > 0 && asset.SizeBytes <= maxPublicationInteger && isLowerHex(asset.SHA256, 64)
}

func validatePublicationManifest(manifest PublicationManifest) error {
	if manifest.SchemaVersion != 1 || !validUUID(manifest.SeriesID) ||
		!validSlug(manifest.SeriesSlug) || !validSlug(manifest.ChapterSlug) ||
		len(manifest.Pages) < 1 || len(manifest.Pages) > MaxPublicationPages {
		return ErrInvalidPublicationCommand
	}
	for index, page := range manifest.Pages {
		number := index + 1
		if page.PageNumber != number || page.EncodingVersion != 4 ||
			page.EncodingRows < 1 || page.EncodingRows > 32 ||
			page.EncodingColumns < 1 || page.EncodingColumns > 32 ||
			!isLowerHex(page.EncodingSeed, 32) {
			return ErrInvalidPublicationCommand
		}
		prefix := fmt.Sprintf("%s/%s/_v4/%s", manifest.SeriesSlug, manifest.ChapterSlug, assetVersionV4(page.EncodingSeed))
		primary := fmt.Sprintf("%s/%04d.mrt", prefix, number)
		if !validatePublicationAsset(page.PublicationAsset, primary, page.EncodingRows, page.EncodingColumns) {
			return ErrInvalidPublicationCommand
		}
		if page.Responsive != nil {
			responsive := fmt.Sprintf("%s/w%d/%04d.mrt", prefix, page.Responsive.Width, number)
			if !validatePublicationAsset(*page.Responsive, responsive, page.EncodingRows, page.EncodingColumns) ||
				page.Responsive.Width >= page.Width || page.Responsive.Height > page.Height {
				return ErrInvalidPublicationCommand
			}
		}
	}
	return nil
}

func publicationAssetMap(asset PublicationAsset) map[string]any {
	return map[string]any{
		"height": asset.Height, "image_path": asset.ImagePath, "sha256": asset.SHA256,
		"size_bytes": asset.SizeBytes, "width": asset.Width,
	}
}

func publicationManifestMap(manifest PublicationManifest) map[string]any {
	pages := make([]any, 0, len(manifest.Pages))
	for _, page := range manifest.Pages {
		item := publicationAssetMap(page.PublicationAsset)
		item["page_number"] = page.PageNumber
		item["encoding_version"] = page.EncodingVersion
		item["encoding_rows"] = page.EncodingRows
		item["encoding_columns"] = page.EncodingColumns
		item["encoding_seed"] = page.EncodingSeed
		if page.Responsive == nil {
			item["responsive"] = nil
		} else {
			item["responsive"] = publicationAssetMap(*page.Responsive)
		}
		pages = append(pages, item)
	}
	return map[string]any{
		"chapter_slug":   manifest.ChapterSlug,
		"pages":          pages,
		"schema_version": manifest.SchemaVersion,
		"series_id":      manifest.SeriesID,
		"series_slug":    manifest.SeriesSlug,
	}
}

func publicationUnsignedMap(command PublicationCommand) map[string]any {
	var chapterID any
	if command.ChapterID != nil {
		chapterID = *command.ChapterID
	}
	var title any
	if command.Title != nil {
		title = *command.Title
	}
	return map[string]any{
		"actor_id":             command.ActorID,
		"chapter_id":           chapterID,
		"chapter_number":       command.ChapterNumber,
		"expected_revision":    command.ExpectedRevision,
		"idempotency_key":      command.IdempotencyKey,
		"ingestion_generation": command.IngestionGeneration,
		"manifest":             publicationManifestMap(command.Manifest),
		"media_generation":     command.MediaGeneration,
		"media_operation_id":   command.MediaOperationID,
		"operation_id":         command.OperationID,
		"schema_version":       command.SchemaVersion,
		"source_revision":      command.SourceRevision,
		"title":                title,
	}
}

func writeJSONStringASCII(buf *bytes.Buffer, value string) {
	buf.WriteByte('"')
	for _, ch := range value {
		switch ch {
		case '"':
			buf.WriteString(`\"`)
		case '\\':
			buf.WriteString(`\\`)
		case '\b':
			buf.WriteString(`\b`)
		case '\f':
			buf.WriteString(`\f`)
		case '\n':
			buf.WriteString(`\n`)
		case '\r':
			buf.WriteString(`\r`)
		case '\t':
			buf.WriteString(`\t`)
		default:
			if ch >= 0x20 && ch <= 0x7e {
				buf.WriteRune(ch)
			} else if ch <= 0xffff {
				fmt.Fprintf(buf, `\u%04x`, ch)
			} else {
				hi, lo := utf16.EncodeRune(ch)
				fmt.Fprintf(buf, `\u%04x\u%04x`, hi, lo)
			}
		}
	}
	buf.WriteByte('"')
}

func writeCanonicalJSON(buf *bytes.Buffer, value any) error {
	switch item := value.(type) {
	case nil:
		buf.WriteString("null")
	case string:
		writeJSONStringASCII(buf, item)
	case int:
		buf.WriteString(strconv.Itoa(item))
	case int64:
		buf.WriteString(strconv.FormatInt(item, 10))
	case []any:
		buf.WriteByte('[')
		for index, child := range item {
			if index > 0 {
				buf.WriteByte(',')
			}
			if err := writeCanonicalJSON(buf, child); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(item))
		for key := range item {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		buf.WriteByte('{')
		for index, key := range keys {
			if index > 0 {
				buf.WriteByte(',')
			}
			writeJSONStringASCII(buf, key)
			buf.WriteByte(':')
			if err := writeCanonicalJSON(buf, item[key]); err != nil {
				return err
			}
		}
		buf.WriteByte('}')
	default:
		return fmt.Errorf("unsupported canonical publication type %T", value)
	}
	return nil
}

func canonicalDigest(value any) (string, error) {
	var buf bytes.Buffer
	if err := writeCanonicalJSON(&buf, value); err != nil {
		return "", err
	}
	sum := sha256.Sum256(buf.Bytes())
	return hex.EncodeToString(sum[:]), nil
}

// PublicationCommandDigests validates the unsigned command shape and returns the
// cross-language canonical digests. It does not accept or repair a submitted
// payload digest; ValidatePublicationCommand performs that comparison.
func PublicationCommandDigests(command PublicationCommand) (manifestDigest string, payloadDigest string, err error) {
	if command.SchemaVersion != 1 || !validUUID(command.IdempotencyKey) || !validUUID(command.OperationID) ||
		!validUUID(command.ActorID) || !validUUID(command.MediaOperationID) || command.SourceRevision < 1 ||
		command.SourceRevision > maxPublicationInteger || command.IngestionGeneration < 1 ||
		command.IngestionGeneration > maxPublicationInteger || command.MediaGeneration < 1 ||
		command.MediaGeneration > maxPublicationInteger || !validChapterNumber(command.ChapterNumber) ||
		!validTitle(command.Title) {
		return "", "", ErrInvalidPublicationCommand
	}
	if command.ChapterID == nil {
		if command.ExpectedRevision != 0 {
			return "", "", ErrInvalidPublicationCommand
		}
	} else if !validUUID(*command.ChapterID) || command.ExpectedRevision < 1 || command.ExpectedRevision >= maxPublicationInteger {
		return "", "", ErrInvalidPublicationCommand
	}
	if err := validatePublicationManifest(command.Manifest); err != nil {
		return "", "", err
	}
	manifestDigest, err = canonicalDigest(publicationManifestMap(command.Manifest))
	if err != nil {
		return "", "", err
	}
	payloadDigest, err = canonicalDigest(publicationUnsignedMap(command))
	if err != nil {
		return "", "", err
	}
	return manifestDigest, payloadDigest, nil
}

// ValidatePublicationCommand independently enforces the P06 v1 command shape
// and canonical digests inside Catalog. It does not authenticate the workload or
// actor; the private HTTP boundary performs those checks before calling Store.
func ValidatePublicationCommand(command PublicationCommand) (manifestDigest string, payloadDigest string, err error) {
	if !isLowerHex(command.PayloadSHA256, 64) {
		return "", "", ErrInvalidPublicationCommand
	}
	manifestDigest, payloadDigest, err = PublicationCommandDigests(command)
	if err != nil {
		return "", "", err
	}
	if payloadDigest != command.PayloadSHA256 {
		return "", "", ErrPublicationPayloadDigest
	}
	return manifestDigest, payloadDigest, nil
}
