#!/usr/bin/env python3
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent / "scripts"
REPO_ROOT = TEST_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))
from validate_m331_benchmark import build_report, load_json, validate_manifest  # noqa: E402


class BenchmarkValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_json(REPO_ROOT / "configs/video-m3.3.1-benchmark.json")

    def empty_manifest(self):
        return {key: copy.deepcopy(value) for key, value in self.config.items() if key in {"version", "milestone", "purpose", "acceptance_role", "samples"}}

    def valid_sample(self, split="development", privacy="approved_local_only", status="complete"):
        return {
            "sample_id": "real_0001",
            "item_id": "sv_20260823_ab12cd34",
            "source_sha1": "0123456789abcdef0123456789abcdef01234567",
            "source_kind": "user_video",
            "source_origin": "import",
            "duration_ms": 4000,
            "width": 1920,
            "height": 1080,
            "fps": 29.97,
            "codec": "hevc",
            "capture_time": None,
            "split": split,
            "annotation_status": status,
            "privacy_status": privacy,
            "annotations": {
                "annotator_id": "local_a",
                "annotated_at": "2026-08-23T12:00:00+08:00",
                "shot_boundaries": [{"time_ms": 1000, "confidence": 0.9}, {"time_ms": 2500, "confidence": 0.8}],
                "transition_types": [{"value": "hard_cut", "time_ms": 1000, "confidence": 0.9}],
                "camera_moves": [{"value": "pan", "window_ms": [0, 900], "confidence": 0.7}],
                "color_continuity": {"value": "gradual_drift", "confidence": 0.8}
            }
        }

    def test_empty_manifest_is_valid_and_honest(self):
        manifest = self.empty_manifest()
        self.assertEqual(validate_manifest(manifest, self.config), [])
        report = build_report(manifest, self.config)
        self.assertTrue(report["ok"])
        self.assertEqual(report["total_samples"], 0)
        self.assertEqual(report["eligible_samples"], 0)
        self.assertEqual(report["excluded_samples"], 0)
        self.assertFalse(report["metrics"]["available"])
        self.assertIn("unavailable", report["metrics"]["reason"])

    def test_valid_synthetic_metadata_and_holdout_report(self):
        manifest = self.empty_manifest()
        sample = self.valid_sample(split="holdout")
        manifest["samples"] = [sample]
        self.assertEqual(validate_manifest(manifest, self.config), [])
        report = build_report(manifest, self.config)
        self.assertEqual(report["eligible_samples"], 1)
        self.assertEqual(report["counts"]["by_split"], {"holdout": 1})
        self.assertFalse(report["metrics"]["available"])
        self.assertIn("not implemented", report["metrics"]["reason"])

    def test_duplicate_sha_and_cross_split_duplicate_rejected(self):
        manifest = self.empty_manifest()
        first = self.valid_sample("development")
        second = self.valid_sample("validation")
        second["sample_id"] = "real_0002"
        second["item_id"] = "sv_20260823_ef56gh78"  # invalid item id also proves independent validation
        manifest["samples"] = [first, second]
        errors = validate_manifest(manifest, self.config)
        self.assertTrue(any("duplicate source_sha1" in error for error in errors))

    def test_duplicate_ids_rejected(self):
        manifest = self.empty_manifest()
        sample = self.valid_sample()
        manifest["samples"] = [sample, copy.deepcopy(sample)]
        errors = validate_manifest(manifest, self.config)
        self.assertTrue(any("duplicate sample_id" in error for error in errors))
        self.assertTrue(any("duplicate item_id" in error for error in errors))

    def test_invalid_metadata_rejected(self):
        manifest = self.empty_manifest()
        sample = self.valid_sample()
        sample.update({"duration_ms": 0, "width": -1, "height": 1.5, "fps": float("nan"), "split": "test", "privacy_status": "public"})
        manifest["samples"] = [sample]
        errors = validate_manifest(manifest, self.config)
        self.assertTrue(any("duration_ms" in error for error in errors))
        self.assertTrue(any("width" in error for error in errors))
        self.assertTrue(any("fps" in error for error in errors))
        self.assertTrue(any("invalid split" in error for error in errors))

    def test_privacy_exclusion_is_reported_not_eligible(self):
        manifest = self.empty_manifest()
        manifest["samples"] = [self.valid_sample(privacy="excluded")]
        self.assertEqual(validate_manifest(manifest, self.config), [])
        report = build_report(manifest, self.config)
        self.assertEqual(report["eligible_samples"], 0)
        self.assertEqual(report["excluded_samples"], 1)
        self.assertEqual(report["counts"]["by_privacy_status"], {"excluded": 1})

    def test_invalid_annotation_labels_confidence_and_boundaries(self):
        manifest = self.empty_manifest()
        sample = self.valid_sample()
        sample["annotations"]["transition_types"][0]["value"] = "wipe"
        sample["annotations"]["camera_moves"][0]["confidence"] = 1.2
        sample["annotations"]["shot_boundaries"] = [{"time_ms": 1000}, {"time_ms": 900}]
        sample["annotations"]["color_continuity"]["value"] = "semantic"
        manifest["samples"] = [sample]
        errors = validate_manifest(manifest, self.config)
        self.assertTrue(any("invalid transition_types label" in error for error in errors))
        self.assertTrue(any("confidence" in error for error in errors))
        self.assertTrue(any("unordered shot boundary" in error for error in errors))
        self.assertTrue(any("invalid color_continuity" in error for error in errors))

    def test_media_paths_and_credentials_rejected(self):
        manifest = self.empty_manifest()
        sample = self.valid_sample()
        sample["notes"] = "source /private/video.mp4"
        sample["api_key"] = "redacted"
        manifest["samples"] = [sample]
        errors = validate_manifest(manifest, self.config)
        self.assertTrue(any("forbidden" in error for error in errors))

    def test_capture_time_must_be_null_or_iso(self):
        manifest = self.empty_manifest()
        sample = self.valid_sample()
        sample["capture_time"] = "yesterday"
        manifest["samples"] = [sample]
        errors = validate_manifest(manifest, self.config)
        self.assertTrue(any("capture_time" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
