#!/usr/bin/env python3
"""M3.2 fixture contract tests; no transition/camera detector is tested here."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS = TEST_DIR.parent / "scripts"
REPO_ROOT = TEST_DIR.parents[2]
sys.path.insert(0, str(SCRIPTS))

import m3_2_fixtures as fixtures  # noqa: E402
from evaluate_m32_fixtures import compare_probe  # noqa: E402


class TestFixtureSpecifications(unittest.TestCase):
    def test_six_required_fixtures_and_independent_ground_truth(self):
        suite = fixtures.load_fixture_specs()
        self.assertEqual(
            {item["fixture_id"] for item in suite["fixtures"]},
            {"static_hard_cut", "static_dissolve", "static_fade", "pan_horizontal", "zoom_in", "no_motion"},
        )
        for item in suite["fixtures"]:
            self.assertEqual(item["ground_truth_source"], "synthetic_spec")
            self.assertIn("shot_boundaries_ms", item)
            self.assertIn("transition_ground_truth", item)
            self.assertIn("camera_ground_truth", item)

    def test_invalid_ground_truth_source_rejected(self):
        suite = fixtures.load_fixture_specs()
        item = dict(suite["fixtures"][0])
        item["ground_truth_source"] = "algorithm_output"
        with self.assertRaises(ValueError):
            fixtures.validate_fixture_spec(item)


class TestFixtureRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = fixtures.load_fixture_specs()

    def test_generate_all_fixtures_and_probe(self):
        with tempfile.TemporaryDirectory(prefix="stylevault_m32_test_") as output_dir:
            for spec in self.suite["fixtures"]:
                result = fixtures.probe_fixture(spec, output_dir)
                self.assertTrue(os.path.exists(result["video_path"]))
                self.assertEqual(result["fixture_id"], spec["fixture_id"])
                self.assertEqual(compare_probe(spec, result["probe"]), [])
            self.assertFalse(list(Path(output_dir).glob("*.png")))

    def test_fixture_generation_is_reproducible(self):
        spec = self.suite["fixtures"][0]
        with tempfile.TemporaryDirectory(prefix="stylevault_m32_test_") as first, tempfile.TemporaryDirectory(prefix="stylevault_m32_test_") as second:
            one = fixtures.probe_fixture(spec, first)
            two = fixtures.probe_fixture(spec, second)
            self.assertEqual(one["probe"]["duration_ms"], two["probe"]["duration_ms"])
            self.assertEqual(one["probe"]["width"], two["probe"]["width"])
            self.assertEqual(one["probe"]["height"], two["probe"]["height"])
            self.assertEqual(one["probe"]["fps"], two["probe"]["fps"])


if __name__ == "__main__":
    unittest.main()
