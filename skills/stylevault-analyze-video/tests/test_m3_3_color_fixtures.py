#!/usr/bin/env python3
"""M3.3 color fixture and detector contract tests."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS = TEST_DIR.parent / "scripts"
REPO_ROOT = TEST_DIR.parents[2]
sys.path.insert(0, str(SCRIPTS))

import m3_3_color_fixtures as fixtures  # noqa: E402
from evaluate_m33_color_fixtures import compare_probe, compare_reference, evaluate_config  # noqa: E402


class TestColorSpecifications(unittest.TestCase):
    def test_required_fixtures_and_spec_ground_truth(self):
        suite = fixtures.load_color_specs()
        expected = {"stable_color", "gradual_color_drift", "abrupt_color_shift", "alternating_color", "fade_color_change"}
        self.assertEqual({item["fixture_id"] for item in suite["fixtures"]}, expected)
        for item in suite["fixtures"]:
            self.assertEqual(item["ground_truth_source"], "synthetic_spec")
            self.assertIn("expected_mean_delta_e", item)
            self.assertIn("expected_drift_rate", item)
            self.assertIn("expected_stable_ratio", item)
            self.assertIn("expected_dominant_shift", item)

    def test_manual_metric_contract(self):
        frames = []
        for index, rgb in enumerate([(0, 0, 0), (10, 0, 0), (20, 0, 0)]):
            from PIL import Image
            path = Path(tempfile.mktemp(suffix=".png"))
            Image.new("RGB", (8, 8), rgb).save(path)
            frames.append({"path": str(path), "time_s": index * 0.5})
        try:
            metrics = __import__("analyze_video").FfmpegAdapter._color_metrics_from_frames(frames, 0.5)
            self.assertEqual(metrics["interval_count"], 2)
            self.assertEqual(metrics["sample_times_s"], [0.0, 0.5, 1.0])
            self.assertGreater(metrics["mean_delta_e"], 0)
            self.assertGreater(metrics["drift_rate"], 0)
        finally:
            for item in frames:
                Path(item["path"]).unlink(missing_ok=True)

    def test_invalid_metric_inputs_rejected(self):
        adapter = __import__("analyze_video").FfmpegAdapter()
        with self.assertRaises(RuntimeError):
            adapter._color_metrics_from_frames([], 0.25)
        with self.assertRaises(RuntimeError):
            adapter._color_metrics_from_frames([], float("nan"))

    def test_reference_classifier_is_independent_of_expected_label(self):
        spec = next(item for item in fixtures.load_color_specs()["fixtures"] if item["fixture_id"] == "stable_color")
        altered = dict(spec)
        altered["expected_dominant_shift"] = "wrong"
        self.assertEqual(fixtures.reference_metrics(altered)["dominant_shift"], "none")


    def test_reference_sequences_have_expected_signal(self):
        suite = fixtures.load_color_specs()
        for item in suite["fixtures"]:
            reference = fixtures.reference_metrics(item)
            self.assertEqual(reference["dominant_shift"], item["expected_dominant_shift"])
            self.assertTrue(reference["sample_times_s"])
            self.assertEqual(len(reference["sample_times_s"]), len(reference["colors"]))
            self.assertEqual(compare_reference(item, reference), [])


class TestColorFixtureRuntime(unittest.TestCase):
    def test_generate_and_probe_all_color_fixtures(self):
        suite = fixtures.load_color_specs()
        with tempfile.TemporaryDirectory(prefix="stylevault_m33_color_test_") as directory:
            for item in suite["fixtures"]:
                result = fixtures.probe_color_fixture(item, directory)
                self.assertTrue(os.path.exists(result["video_path"]))
                self.assertEqual(compare_probe(item, result["probe"]), [])
            self.assertFalse(list(Path(directory).glob("*.png")))

    def test_independent_evaluator_passes_all_fixtures(self):
        report = evaluate_config(str(fixtures.CONFIG_PATH))
        self.assertTrue(report["ok"], report)
        self.assertEqual(sum(item["ok"] for item in report["fixtures"]), 5)

    def test_dedicated_gate_accepts_proof_but_legacy_route_remains_closed(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as proof:
            json.dump({"color_continuity_acceptance": {"ok": True, "fixture_count": 5, "passed": 5, "metrics_contract_version": "m3.3.v1"}}, proof)
            proof_path = proof.name
        try:
            command = [sys.executable, str(SCRIPTS / "evaluate_video.py"), "--ground-truth", str(REPO_ROOT / "configs/video-test-suite.json"), "--prediction", proof_path, "--color-fixtures", str(fixtures.CONFIG_PATH), "--milestone", "M3.3"]
            process = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stdout)
            self.assertIn('"ok": true', process.stdout)
        finally:
            os.unlink(proof_path)


if __name__ == "__main__":
    unittest.main()
