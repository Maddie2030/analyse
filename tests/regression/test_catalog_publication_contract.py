"""Publication wire/evidence regressions; no mocked DB/storage acceptance claims."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared"))
FIXTURES = ROOT / "contracts/catalog/v1/fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class CatalogPublicationContractTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module("shared.catalog_publication_contract")
        except ModuleNotFoundError:
            self.fail("P06.2 publication contract is not implemented")
        self.command = fixture("publication.json")
        self.actor = self.command["actor_id"]

    def unsigned(self):
        result = deepcopy(self.command)
        del result["payload_sha256"]
        return result

    def reject(self, code, function, *args, **kwargs):
        with self.assertRaises(self.api.PublicationContractError) as caught:
            function(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def test_sealing_matches_independent_unicode_digest_vector(self):
        original = self.unsigned()
        before = deepcopy(original)
        result = self.api.seal_command(original)
        self.assertEqual(self.command, result)
        self.assertEqual(before, original)
        self.assertEqual(
            "eda3b0711cb119f12b25d48913cecec4e911108d984b9afc07ffb75af3ffda45",
            self.api.manifest_digest(original["manifest"]),
        )

    def test_sealed_and_validated_snapshots_do_not_alias_caller_memory(self):
        unsigned = self.unsigned()
        sealed = self.api.seal_command(unsigned)
        validated = self.api.validate_command(sealed)
        unsigned["manifest"]["pages"].clear()
        sealed["manifest"]["pages"][0]["responsive"]["width"] = 1
        self.assertEqual(self.command, validated)

    def test_python_builder_does_not_coerce_non_json_container_types(self):
        value = self.unsigned()
        value["manifest"]["pages"] = tuple(value["manifest"]["pages"])
        self.reject("invalid_manifest", self.api.seal_command, value)

    def test_escaped_duplicate_keys_and_deep_json_fail_closed(self):
        raw = json.dumps(self.command)
        duplicate = raw.replace('"source_revision": 3', '"source_revision": 3, "source_\\u0072evision": 3')
        self.reject("invalid_command", self.api.decode_command, duplicate.encode())
        self.reject("invalid_command", self.api.decode_command, b"[" * 2000 + b"0" + b"]" * 2000)

    def test_moderate_depth_json_cannot_escape_as_snapshot_recursion_error(self):
        raw = json.dumps(self.command)
        nested = raw.replace(json.dumps(self.command["title"]), "[" * 510 + "0" + "]" * 510)
        self.reject("invalid_command", self.api.decode_command, nested.encode())

    def test_evidence_shape_and_integer_types_are_not_guessed(self):
        media = fixture("media-receipt.json")
        media["page_count"] = True
        self.reject("invalid_media_receipt", self.api.validate_media_evidence, self.command, media, actor_id=self.actor)
        media = fixture("media-receipt.json")
        media["verified"] = True
        self.reject("invalid_media_receipt", self.api.validate_media_evidence, self.command, media, actor_id=self.actor)
        receipt = fixture("catalog-receipt.json")
        receipt["chapter_revision"] = True
        self.reject("invalid_catalog_receipt", self.api.replay_receipt, self.command, receipt, actor_id=self.actor)

    def test_replacement_replay_cannot_return_another_chapter(self):
        value = self.unsigned()
        value["chapter_id"] = "66666666-6666-4666-8666-666666666666"
        value["expected_revision"] = 4
        command = self.api.seal_command(value)
        receipt = fixture("catalog-receipt.json")
        receipt["payload_sha256"] = command["payload_sha256"]
        receipt["chapter_revision"] = 5
        self.assertEqual(5, self.api.replay_receipt(command, receipt, actor_id=self.actor)["chapter_revision"])
        receipt["chapter_id"] = "88888888-8888-4888-8888-888888888888"
        self.reject("invalid_catalog_receipt", self.api.replay_receipt, command, receipt, actor_id=self.actor)

    def test_missing_or_unknown_fields_cannot_be_silently_defaulted(self):
        for field in self.unsigned():
            with self.subTest(missing=field):
                value = self.unsigned()
                del value[field]
                self.reject("invalid_command", self.api.seal_command, value)
        for key in ("status", "verified", "source_url", "admin", "payload_sha256"):
            with self.subTest(extra=key):
                value = self.unsigned()
                value[key] = "caller supplied"
                self.reject("invalid_command", self.api.seal_command, value)
        value = self.unsigned()
        value["manifest"]["pages"][0]["unexpected"] = True
        self.reject("invalid_manifest", self.api.seal_command, value)

    def test_version_ids_and_fences_are_strict_without_numeric_coercion(self):
        for field in ("source_revision", "ingestion_generation", "media_generation"):
            for invalid in (0, -1, True, 1.0, "1", None, 9007199254740992):
                with self.subTest(field=field, invalid=invalid):
                    value = self.unsigned()
                    value[field] = invalid
                    self.reject("invalid_command", self.api.seal_command, value)
        for invalid in (0, True, 1.0, 2, "1"):
            value = self.unsigned()
            value["schema_version"] = invalid
            self.reject("invalid_command", self.api.seal_command, value)
        for field in ("idempotency_key", "operation_id", "actor_id", "media_operation_id"):
            value = self.unsigned()
            value[field] = "00000000-0000-0000-0000-000000000000"
            self.reject("invalid_command", self.api.seal_command, value)

    def test_create_and_replace_require_unambiguous_target_revision(self):
        value = self.unsigned()
        value["expected_revision"] = 1
        self.reject("invalid_command", self.api.seal_command, value)
        value["chapter_id"] = "66666666-6666-4666-8666-666666666666"
        self.assertEqual(1, self.api.seal_command(value)["expected_revision"])
        value["expected_revision"] = 0
        self.reject("invalid_command", self.api.seal_command, value)
        value["expected_revision"] = 9007199254740991
        self.reject("invalid_command", self.api.seal_command, value)

    def test_chapter_number_and_title_preserve_wire_identity(self):
        for invalid in (12.5, "12.5", "012.50", "1e2", "NaN", "-1.00", "1000000.00"):
            value = self.unsigned()
            value["chapter_number"] = invalid
            self.reject("invalid_command", self.api.seal_command, value)
        for invalid in ("x" * 256, "bad\x00title", "\ud800", True):
            value = self.unsigned()
            value["title"] = invalid
            self.reject("invalid_command", self.api.seal_command, value)
        for valid in ("0.00", "999999.99"):
            value = self.unsigned()
            value["chapter_number"] = valid
            value["title"] = None
            self.assertEqual(valid, self.api.seal_command(value)["chapter_number"])

    def test_pages_require_complete_ordered_nonempty_evidence(self):
        value = self.unsigned()
        value["manifest"]["pages"] = []
        self.reject("invalid_manifest", self.api.seal_command, value)
        value = self.unsigned()
        value["manifest"]["pages"][0]["page_number"] = 2
        self.reject("invalid_manifest", self.api.seal_command, value)
        value = self.unsigned()
        value["manifest"]["pages"] *= 2
        self.reject("invalid_manifest", self.api.seal_command, value)
        for field in ("sha256", "size_bytes", "encoding_seed", "responsive"):
            value = self.unsigned()
            del value["manifest"]["pages"][0][field]
            self.reject("invalid_manifest", self.api.seal_command, value)

    def test_final_page_bound_accepts_full_manifest_and_never_truncates(self):
        value = self.unsigned()
        page = value["manifest"]["pages"][0]
        page["responsive"] = None
        prefix = page["image_path"].rsplit("/", 1)[0]
        value["manifest"]["pages"] = [
            dict(page, page_number=n, image_path=f"{prefix}/{n:04d}.mrt")
            for n in range(1, 4097)
        ]
        self.assertEqual(4096, len(self.api.seal_command(value)["manifest"]["pages"]))
        value["manifest"]["pages"].append(dict(page, page_number=4097, image_path=f"{prefix}/4097.mrt"))
        self.reject("manifest_too_large", self.api.seal_command, value)

    def test_object_paths_must_match_target_seed_page_and_derivative(self):
        paths = ("/etc/passwd", "C:/Users/reader/private", "https://nas/object", "../escape",
                 "images/" + self.command["manifest"]["pages"][0]["image_path"],
                 "series/chapter/%2e%2e/file.mrt", "series\\chapter\\file.mrt")
        for path in paths:
            value = self.unsigned()
            value["manifest"]["pages"][0]["image_path"] = path
            self.reject("invalid_manifest", self.api.seal_command, value)
        for field, invalid in (("series_slug", "other-series"), ("chapter_slug", "other-chapter"), ("series_slug", "../series")):
            value = self.unsigned()
            value["manifest"][field] = invalid
            self.reject("invalid_manifest", self.api.seal_command, value)
        value = self.unsigned()
        value["manifest"]["pages"][0]["encoding_seed"] = "00" * 16
        self.reject("invalid_manifest", self.api.seal_command, value)

    def test_schema_distinguishes_primary_and_responsive_image_paths(self):
        schema = json.loads((ROOT / "contracts/catalog/v1/types.schema.json").read_text())
        primary_pattern = re.compile(schema["$defs"]["page"]["properties"]["image_path"]["pattern"])
        responsive_pattern = re.compile(schema["$defs"]["asset"]["properties"]["image_path"]["pattern"])
        page = self.command["manifest"]["pages"][0]

        self.assertIsNotNone(primary_pattern.fullmatch(page["image_path"]))
        self.assertIsNone(primary_pattern.fullmatch(page["responsive"]["image_path"]))
        self.assertIsNotNone(responsive_pattern.fullmatch(page["responsive"]["image_path"]))
        self.assertIsNone(responsive_pattern.fullmatch(page["image_path"]))

    def test_publication_slug_rules_match_existing_catalog_admin_rules(self):
        for slug in ("series_name", "series-", "series--name"):
            value = self.unsigned()
            manifest = value["manifest"]
            manifest["series_slug"] = slug
            page = manifest["pages"][0]
            page["image_path"] = page["image_path"].replace("fixture-series/", slug + "/")
            page["responsive"]["image_path"] = page["responsive"]["image_path"].replace("fixture-series/", slug + "/")
            self.reject("invalid_manifest", self.api.seal_command, value)

    def test_v4_dimension_grid_and_checksum_errors_are_rejected(self):
        for field, invalid in (("width", 20001), ("height", 40001), ("width", 0),
                               ("encoding_rows", 33), ("encoding_columns", 0),
                               ("encoding_version", 3), ("size_bytes", 0),
                               ("sha256", "not-a-checksum")):
            value = self.unsigned()
            value["manifest"]["pages"][0][field] = invalid
            self.reject("invalid_manifest", self.api.seal_command, value)
        value = self.unsigned()
        value["manifest"]["pages"][0]["height"] = 2
        self.reject("invalid_manifest", self.api.seal_command, value)

    def test_responsive_objects_are_all_or_none_and_share_decoding_grid(self):
        for invalid in ({}, {"image_path": "image.mrt"}, True):
            value = self.unsigned()
            value["manifest"]["pages"][0]["responsive"] = invalid
            self.reject("invalid_manifest", self.api.seal_command, value)
        value = self.unsigned()
        value["manifest"]["pages"][0]["responsive"]["height"] = 2
        self.reject("invalid_manifest", self.api.seal_command, value)
        value = self.unsigned()
        value["manifest"]["pages"][0]["responsive"] = None
        self.assertIsNone(self.api.seal_command(value)["manifest"]["pages"][0]["responsive"])

    def test_changed_payload_cannot_keep_the_old_digest(self):
        self.command["title"] = "Changed title"
        self.reject("payload_digest_mismatch", self.api.validate_command, self.command)

    def test_decode_rejects_ambiguous_or_noncanonical_json_types(self):
        raw = json.dumps(self.command)
        for invalid in ('{"schema_version":1,' + raw[1:], raw + " {}", raw.replace('"source_revision": 3', '"source_revision": 3.0'), raw.replace('"source_revision": 3', '"source_revision": NaN')):
            self.reject("invalid_command", self.api.decode_command, invalid.encode())
        self.reject("invalid_command", self.api.decode_command, b'\xff')
        self.assertEqual(self.command, self.api.decode_command(raw.encode()))

    def test_oversized_wire_payloads_are_rejected_before_processing(self):
        self.reject("request_too_large", self.api.decode_command, b" " * (4 * 1024 * 1024 + 1))
        value = self.unsigned()
        value["title"] = "x" * (4 * 1024 * 1024)
        self.reject("request_too_large", self.api.seal_command, value)

    def test_complete_media_evidence_matches_without_owning_publication(self):
        media = fixture("media-receipt.json")
        accepted = self.api.validate_media_evidence(self.command, media, actor_id=self.actor)
        self.assertEqual(self.command, accepted)
        self.assertIsNone(accepted["chapter_id"])
        media["manifest_sha256"] = "00" * 32
        self.assertEqual(self.command, accepted)

    def test_pending_or_failed_media_cannot_prove_completed_output(self):
        for status in ("queued", "processing", "failed", "cancelled"):
            media = fixture("media-receipt.json")
            media["status"] = status
            self.reject("media_not_complete", self.api.validate_media_evidence, self.command, media, actor_id=self.actor)

    def test_media_evidence_is_bound_to_actor_operation_revision_and_generation(self):
        for field, invalid in (("operation_id", "88888888-8888-4888-8888-888888888888"),
                               ("media_operation_id", "88888888-8888-4888-8888-888888888888"),
                               ("actor_id", "88888888-8888-4888-8888-888888888888"),
                               ("source_revision", 2), ("media_generation", 1),
                               ("page_count", 2), ("manifest_sha256", "00" * 32)):
            with self.subTest(field=field):
                media = fixture("media-receipt.json")
                media[field] = invalid
                self.reject("media_evidence_mismatch", self.api.validate_media_evidence, self.command, media, actor_id=self.actor)

    def test_authenticated_actor_must_match_even_for_receipt_replay(self):
        other = "88888888-8888-4888-8888-888888888888"
        self.reject("actor_mismatch", self.api.validate_media_evidence, self.command, fixture("media-receipt.json"), actor_id=other)
        self.reject("actor_mismatch", self.api.replay_receipt, self.command, fixture("catalog-receipt.json"), actor_id=other)

    def test_identical_retry_returns_the_detached_recorded_catalog_result(self):
        receipt = fixture("catalog-receipt.json")
        replay = self.api.replay_receipt(self.command, receipt, actor_id=self.actor)
        self.assertEqual(fixture("catalog-receipt.json"), replay)
        receipt["chapter_id"] = "88888888-8888-4888-8888-888888888888"
        self.assertEqual("66666666-6666-4666-8666-666666666666", replay["chapter_id"])

    def test_same_key_different_body_is_a_conflict_not_another_success(self):
        for field, changed in (("title", "Edited"), ("source_revision", 4), ("ingestion_generation", 8), ("media_generation", 3)):
            with self.subTest(field=field):
                value = self.unsigned()
                value[field] = changed
                changed_command = self.api.seal_command(value)
                self.reject("idempotency_conflict", self.api.replay_receipt, changed_command, fixture("catalog-receipt.json"), actor_id=self.actor)

    def test_catalog_receipt_must_identify_the_same_target_and_result(self):
        for field, changed in (("status", "queued"), ("page_count", 2), ("chapter_revision", 2), ("series_id", "88888888-8888-4888-8888-888888888888"), ("publication_event_id", None)):
            receipt = fixture("catalog-receipt.json")
            receipt[field] = changed
            self.reject("invalid_catalog_receipt", self.api.replay_receipt, self.command, receipt, actor_id=self.actor)
        self.reject("invalid_catalog_receipt", self.api.replay_receipt, self.command, None, actor_id=self.actor)


if __name__ == "__main__":
    unittest.main()
