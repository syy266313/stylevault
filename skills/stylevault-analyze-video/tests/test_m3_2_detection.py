#!/usr/bin/env python3
"""M3.2 frame detector tests on independent synthetic fixtures."""
import json
import math
import os
import subprocess
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


class TestM32Integration(unittest.TestCase):
    def test_analyze_m32_uses_segment_context_and_event_positions(self):
        report = evaluate_config(str(fixtures.CONFIG_PATH))
        for row in report["fixtures"]:
            for item in row["prediction"]["transition_types"] + row["prediction"]["camera_moves"]:
                self.assertIn("segment_index", item)
                self.assertIn("window_ms", item)
            if row["fixture_id"] in {"static_hard_cut", "static_dissolve", "static_fade"}:
                event = row["prediction"]["transition_types"][0]
                self.assertIn("time_s", event)

    def test_analyze_m32_cli_returns_unified_rhythm(self):
        spec = fixtures.load_fixture_specs()["fixtures"][0]
        with tempfile.TemporaryDirectory(prefix="stylevault_m32_cli_") as directory:
            video = fixtures.generate_fixture(spec, directory)
            process = subprocess.run([sys.executable, str(SCRIPTS / "analyze_video.py"), "analyze-m32", video], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(process.stdout)
            self.assertIn("rhythm", payload)
            self.assertIn("params", payload["rhythm"])
            self.assertIn("transition_types", payload["rhythm"]["params"])
            self.assertIn("camera_moves", payload["rhythm"]["params"])

    def test_multi_segment_boundary_context_and_absolute_position(self):
        adapter = av.FfmpegAdapter()
        probe = {"adapter": "ffmpeg", "duration_ms": 4000.0, "width": 160, "height": 90, "fps": 12.0}
        segments = [
            {"index": 1, "start_ms": 0.0, "duration_ms": 2000.0},
            {"index": 2, "start_ms": 2000.0, "duration_ms": 2000.0},
        ]
        frames = [{"path": f"frame-{i}", "time_s": i * 0.5} for i in range(8)]
        transition = {"value": "hard_cut", "confidence": 0.9, "source": "test", "detection_method": "test-window", "candidate": False, "status": "confirmed", "time_s": 2.0}
        camera = {"value": "static", "confidence": 0.9, "source": "test", "detection_method": "test-motion", "candidate": False, "status": "confirmed"}
        with mock.patch.object(adapter, "segment", return_value={"probe": probe, "segments": segments, "cut_times_s": [2.0], "warnings": []}), \
             mock.patch.object(adapter, "sample_frames", return_value=frames), \
             mock.patch.object(adapter, "_detect_transitions", return_value=[transition]) as transition_call, \
             mock.patch.object(adapter, "_detect_camera_moves", return_value=[camera]):
            result = adapter.analyze_m32("multi.mp4")
        self.assertEqual(result["transition_types"][0]["segment_index"], 2)
        self.assertEqual(result["transition_types"][0]["window_ms"], [2000.0, 4000.0])
        self.assertEqual(result["transition_types"][0]["time_s"], 2.0)
        self.assertTrue(transition_call.called)
        self.assertEqual(transition_call.call_args.kwargs["time_offset_s"], 1.75)


class TestM32Contracts(unittest.TestCase):
    def test_invalid_confidence_and_unknown_are_rejected(self):
        spec = fixtures.load_fixture_specs()["fixtures"][0]
        bad = {"transition_types": [{"value": "unknown", "confidence": float("nan"), "source": "x", "detection_method": "x", "candidate": True, "status": "candidate"}], "camera_moves": []}
        errors = compare_detection(spec, bad)
        self.assertTrue(errors)
        self.assertTrue(any("confidence" in error for error in errors))

    def test_event_position_error_is_rejected(self):
        spec = fixtures.load_fixture_specs()["fixtures"][0]
        bad = {"transition_types": [{"value": "hard_cut", "confidence": 0.9, "source": "x", "detection_method": "x", "candidate": False, "status": "confirmed", "time_s": 3.5}], "camera_moves": []}
        errors = compare_detection(spec, bad)
        self.assertTrue(any("position error" in error for error in errors))

    def test_observation_strings_status_and_candidate_are_strict(self):
        spec = fixtures.load_fixture_specs()["fixtures"][0]
        cases = [
            {"value": "", "confidence": 0.9, "source": "x", "detection_method": "x", "candidate": False, "status": "confirmed"},
            {"value": "hard_cut", "confidence": 0.9, "source": "", "detection_method": "x", "candidate": False, "status": "confirmed"},
            {"value": "hard_cut", "confidence": 0.9, "source": "x", "detection_method": "x", "candidate": 0, "status": "confirmed"},
            {"value": "hard_cut", "confidence": 0.9, "source": "x", "detection_method": "x", "candidate": False, "status": "invalid"},
        ]
        for item in cases:
            errors = compare_detection(spec, {"transition_types": [item], "camera_moves": []})
            self.assertTrue(errors, item)

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
