#!/usr/bin/env python3
"""M3.2 frame detector tests on independent synthetic fixtures."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS = TEST_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze_video as av  # noqa: E402
import m3_2_fixtures as fixtures  # noqa: E402
from evaluate_m32_fixtures import compare_detection, evaluate_config  # noqa: E402


class TestM32Acceptance(unittest.TestCase):
    def test_six_of_six_fixture_acceptance(self):
        report = evaluate_config(str(fixtures.CONFIG_PATH))
        self.assertTrue(report["ok"], report)
        self.assertEqual(sum(item["ok"] for item in report["fixtures"]), 6)

    def test_transition_separation_and_camera_false_positive_guards(self):
        report = evaluate_config(str(fixtures.CONFIG_PATH))
        rows = {item["fixture_id"]: item for item in report["fixtures"]}
        self.assertEqual(rows["static_dissolve"]["prediction"]["transition_types"][0]["value"], "dissolve")
        self.assertEqual(rows["static_fade"]["prediction"]["transition_types"][0]["value"], "fade")
        self.assertEqual(rows["pan_horizontal"]["prediction"]["camera_moves"][0]["value"], "pan")
        self.assertEqual(rows["zoom_in"]["prediction"]["camera_moves"][0]["value"], "zoom")
        self.assertEqual(rows["no_motion"]["prediction"]["camera_moves"][0]["value"], "static")

    def test_lower_confidence_threshold_does_not_make_unknown_pass(self):
        report = evaluate_config(str(fixtures.CONFIG_PATH), confidence_threshold=0.99)
        self.assertFalse(report["ok"])
        self.assertTrue(any(not item["ok"] for item in report["fixtures"]))

    def test_sampling_parameter_is_supported(self):
        report = evaluate_config(str(fixtures.CONFIG_PATH), sampling_fps=6.0)
        self.assertTrue(report["ok"], report)


class TestM32Contracts(unittest.TestCase):
    def test_invalid_confidence_and_unknown_are_rejected(self):
        spec = fixtures.load_fixture_specs()["fixtures"][0]
        bad = {"transition_types": [{"value": "unknown", "confidence": float("nan"), "source": "x", "detection_method": "x", "candidate": True, "status": "candidate"}], "camera_moves": []}
        errors = compare_detection(spec, bad)
        self.assertTrue(errors)
        self.assertTrue(any("confidence" in error for error in errors))

    def test_adapter_boundary_checks(self):
        adapter = av.FfmpegAdapter()
        with self.assertRaises(RuntimeError):
            adapter.sample_frames("/does/not/exist.mp4", tempfile.mkdtemp(), sampling_fps=0)
        with self.assertRaises(RuntimeError):
            adapter.analyze_m32("/does/not/exist.mp4", confidence_threshold=float("inf"))
        with mock.patch.object(av.subprocess, "run", side_effect=av.subprocess.TimeoutExpired("ffmpeg", 1)):
            with self.assertRaises(RuntimeError) as error:
                adapter.sample_frames("x.mp4", tempfile.mkdtemp(), sampling_fps=2)
            self.assertIn("超时", str(error.exception))

    def test_observation_provenance_and_finite_confidence(self):
        item = av.FfmpegAdapter._observation("static", 0.8, "ffmpeg+Pillow", "test", 0.7)
        self.assertEqual(item["status"], "confirmed")
        self.assertFalse(item["candidate"])
        with self.assertRaises(RuntimeError):
            av.FfmpegAdapter._observation("static", float("nan"), "x", "x", 0.7)
        with self.assertRaises(RuntimeError):
            av.FfmpegAdapter._observation("static", float("inf"), "x", "x", 0.7)


if __name__ == "__main__":
    unittest.main()
