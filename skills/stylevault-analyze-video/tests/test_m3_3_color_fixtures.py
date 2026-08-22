#!/usr/bin/env python3
"""M3.3 fixture foundation tests; no final detector is implemented here."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS = TEST_DIR.parent / "scripts"
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

    def test_algorithm_output_cannot_be_ground_truth(self):
        suite = fixtures.load_color_specs()
        item = dict(suite["fixtures"][0])
        item["ground_truth_source"] = "algorithm_output"
        with self.assertRaises(ValueError):
            fixtures.validate_color_spec(item)

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


if __name__ == "__main__":
    unittest.main()
