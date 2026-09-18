package model

import "testing"

func fixturePublicationCommand() PublicationCommand {
	title := "天狐 — Café 🚀 <>&\u2028next"
	return PublicationCommand{
		SchemaVersion:       1,
		IdempotencyKey:      "22222222-2222-4222-8222-222222222222",
		OperationID:         "33333333-3333-4333-8333-333333333333",
		ActorID:             "44444444-4444-4444-8444-444444444444",
		SourceRevision:      3,
		IngestionGeneration: 7,
		MediaOperationID:    "55555555-5555-4555-8555-555555555555",
		MediaGeneration:     2,
		ExpectedRevision:    0,
		ChapterNumber:       "12.50",
		Title:               &title,
		Manifest: PublicationManifest{
			SchemaVersion: 1,
			SeriesID:      "11111111-1111-4111-8111-111111111111",
			SeriesSlug:    "fixture-series",
			ChapterSlug:   "chapter-12-5",
			Pages: []PublicationPage{{
				PublicationAsset: PublicationAsset{
					ImagePath: "fixture-series/chapter-12-5/_v4/fd41034df3d3052913b4/0001.mrt",
					Width:     1080, Height: 1600, SizeBytes: 180000,
					SHA256: "abababababababababababababababababababababababababababababababab",
				},
				PageNumber: 1, EncodingVersion: 4, EncodingRows: 4, EncodingColumns: 4,
				EncodingSeed: "0123456789abcdef0123456789abcdef",
				Responsive: &PublicationAsset{
					ImagePath: "fixture-series/chapter-12-5/_v4/fd41034df3d3052913b4/w720/0001.mrt",
					Width:     720, Height: 1067, SizeBytes: 92000,
					SHA256: "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
				},
			}},
		},
		PayloadSHA256: "4a4de87cbc6e05845d033616a757bdf88bf83613dd901d711e95d5bcdf643488",
	}
}

func TestPublicationDigestVectorsMatchPythonContract(t *testing.T) {
	command := fixturePublicationCommand()
	manifestDigest, payloadDigest, err := ValidatePublicationCommand(command)
	if err != nil {
		t.Fatal(err)
	}
	if manifestDigest != "eda3b0711cb119f12b25d48913cecec4e911108d984b9afc07ffb75af3ffda45" {
		t.Fatalf("manifest digest mismatch: %s", manifestDigest)
	}
	if payloadDigest != command.PayloadSHA256 {
		t.Fatalf("payload digest mismatch: %s", payloadDigest)
	}
}

func TestPublicationRejectsPathThatDoesNotMatchV4Identity(t *testing.T) {
	command := fixturePublicationCommand()
	command.Manifest.Pages[0].ImagePath = "other/chapter/_v4/fd41034df3d3052913b4/0001.mrt"
	if _, _, err := ValidatePublicationCommand(command); err == nil {
		t.Fatal("expected invalid manifest path")
	}
}

func TestPublicationRejectsTamperedPayloadDigest(t *testing.T) {
	command := fixturePublicationCommand()
	command.PayloadSHA256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	if _, _, err := ValidatePublicationCommand(command); err == nil {
		t.Fatal("expected payload digest mismatch")
	}
}
