package cloudfrontcookie

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
)

var signedCookieNames = []string{"CloudFront-Policy", "CloudFront-Signature", "CloudFront-Key-Pair-Id", "CloudFront-Hash-Algorithm"}

type Signer struct {
	privateKey   *rsa.PrivateKey
	publicKeyID  string
	baseURL      string
	cookieDomain string
	ttl          time.Duration
}

type policyEnvelope struct {
	Statement []policyStatement `json:"Statement"`
}
type policyStatement struct {
	Resource  string          `json:"Resource"`
	Condition policyCondition `json:"Condition"`
}
type policyCondition struct {
	DateLessThan epochCondition `json:"DateLessThan"`
}
type epochCondition struct {
	EpochTime int64 `json:"AWS:EpochTime"`
}

func New(privateKeyPEM, publicKeyID, baseURL, cookieDomain string, ttl time.Duration) (*Signer, error) {
	privateKeyPEM = strings.TrimSpace(privateKeyPEM)
	publicKeyID = strings.TrimSpace(publicKeyID)
	baseURL = strings.TrimRight(strings.TrimSpace(baseURL), "/")
	cookieDomain = strings.TrimSpace(cookieDomain)
	if privateKeyPEM == "" || publicKeyID == "" || baseURL == "" || cookieDomain == "" {
		return nil, errors.New("cloudfront cookie signer is incomplete")
	}
	if !strings.HasPrefix(baseURL, "https://") {
		return nil, errors.New("cloudfront resource base URL must use https")
	}
	block, _ := pem.Decode([]byte(privateKeyPEM))
	if block == nil {
		return nil, errors.New("cloudfront private key is not PEM")
	}
	var key *rsa.PrivateKey
	if parsed, err := x509.ParsePKCS1PrivateKey(block.Bytes); err == nil {
		key = parsed
	} else if anyKey, err := x509.ParsePKCS8PrivateKey(block.Bytes); err == nil {
		var ok bool
		key, ok = anyKey.(*rsa.PrivateKey)
		if !ok {
			return nil, errors.New("cloudfront private key is not RSA")
		}
	} else {
		return nil, errors.New("cloudfront private key cannot be parsed")
	}
	if ttl <= 0 {
		ttl = 5 * time.Minute
	}
	return &Signer{privateKey: key, publicKeyID: publicKeyID, baseURL: baseURL, cookieDomain: cookieDomain, ttl: ttl}, nil
}

func cfBase64(raw []byte) string {
	s := base64.StdEncoding.EncodeToString(raw)
	s = strings.ReplaceAll(s, "+", "-")
	s = strings.ReplaceAll(s, "=", "_")
	s = strings.ReplaceAll(s, "/", "~")
	return s
}

func (s *Signer) cookie(name, value string) *http.Cookie {
	return &http.Cookie{
		Name:     name,
		Value:    value,
		Path:     "/",
		Domain:   s.cookieDomain,
		Secure:   true,
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
	}
}

// CookiesForChapter creates a CloudFront custom-policy signed cookie restricted
// to one immutable chapter prefix. CloudFront performs this viewer authorization
// before serving cache hits, while MReader's short-lived grant remains required
// by image-edge on an origin miss.
func (s *Signer) CookiesForChapter(seriesSlug, chapterSlug string, now time.Time) ([]*http.Cookie, error) {
	seriesSlug = strings.Trim(strings.TrimSpace(seriesSlug), "/")
	chapterSlug = strings.Trim(strings.TrimSpace(chapterSlug), "/")
	if seriesSlug == "" || chapterSlug == "" || strings.Contains(seriesSlug, "..") || strings.Contains(chapterSlug, "..") {
		return nil, errors.New("invalid chapter resource")
	}
	resource := fmt.Sprintf("%s/%s/%s/*", s.baseURL, seriesSlug, chapterSlug)
	policy := policyEnvelope{Statement: []policyStatement{{
		Resource:  resource,
		Condition: policyCondition{DateLessThan: epochCondition{EpochTime: now.Add(s.ttl).Unix()}},
	}}}
	raw, err := json.Marshal(policy)
	if err != nil {
		return nil, err
	}
	hash := sha256.Sum256(raw)
	sig, err := rsa.SignPKCS1v15(rand.Reader, s.privateKey, crypto.SHA256, hash[:])
	if err != nil {
		return nil, err
	}
	return []*http.Cookie{
		s.cookie("CloudFront-Policy", cfBase64(raw)),
		s.cookie("CloudFront-Signature", cfBase64(sig)),
		s.cookie("CloudFront-Key-Pair-Id", s.publicKeyID),
		s.cookie("CloudFront-Hash-Algorithm", "SHA256"),
	}, nil
}

// ClearCookies returns immediate expiration cookies for the CloudFront viewer
// authorization cookies. This is called on explicit sign-out so the CDN access
// lifetime does not unnecessarily survive the user's browser session.
func (s *Signer) ClearCookies() []*http.Cookie {
	out := make([]*http.Cookie, 0, len(signedCookieNames))
	for _, name := range signedCookieNames {
		c := s.cookie(name, "")
		c.MaxAge = -1
		c.Expires = time.Unix(1, 0).UTC()
		out = append(out, c)
	}
	return out
}
