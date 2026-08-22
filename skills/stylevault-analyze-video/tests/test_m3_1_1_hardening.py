#!/usr/bin/env python3
"""M3.1.1 加固测试：缺失字段即失败、NaN/Infinity 拒绝、probe 健壮性、M3.3 门控。

不依赖真实 ffmpeg（当前未安装）；ffmpeg/ffprobe 行为用 unittest.mock 模拟。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)          # stylevault-analyze-video
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REPO_ROOT = os.path.dirname(os.path.dirname(SKILL_DIR))  # 仓库根
sys.path.insert(0, SCRIPTS)

import analyze_video as av  # noqa: E402


def load_suite():
    return json.load(open(os.path.join(REPO_ROOT, "configs", "video-test-suite.json")))


def build_prediction(suite):
    """构造与 ground truth 完全匹配的预测（含 segments），供缺失字段测试删字段用。"""
    pred = {}
    for s in suite["samples"]:
        gt = s["ground_truth"]
        avg = gt["avg_shot_ms"]
        n = gt["shot_count"]
        pred[s["id"]] = {
            "probe": {
                "duration_ms": round(avg * n, 3),
                "segments": [
                    {"index": i + 1, "start_ms": round(i * avg, 3), "duration_ms": round(avg, 3)}
                    for i in range(n)
                ],
            },
            "rhythm": {
                "status": "partial",
                "overall_pace": av.derive_overall_pace(avg),
                "params": {
                    "shot_count": n,
                    "avg_shot_ms": avg,
                    "shot_length_distribution": {
                        "p10": gt["shot_length_ms"]["p10"],
                        "p50": gt["shot_length_ms"]["p50"],
                        "p90": gt["shot_length_ms"]["p90"],
                        "buckets": {},
                    },
                    "transition_types": [{"value": "hard_cut", "confidence": 0.9,
                                          "source": "ffmpeg", "detection_method": "scdet"}],
                    "camera_moves": [{"value": "static", "confidence": 0.9,
                                      "source": "ffmpeg", "detection_method": "motion"}],
                    "pace_density": {"cuts_per_min": 1.0, "segment_density": 1.0},
                    "color_continuity": {"status": "not_started"},
                },
                "summary": "hardening test",
            },
        }
    return pred


def full_rhythm(**overrides):
    """构造合法的完整 rhythm，支持点路径覆盖（如 params.avg_shot_ms）。"""
    rhythm = {
        "status": "partial",
        "overall_pace": "medium",
        "coverage": {"probe": {"confidence": 1.0, "source": "x", "detection_method": "y"}},
        "params": {
            "avg_shot_ms": 2000.0,
            "shot_count": 5,
            "shot_length_distribution": {"p10": 1000.0, "p50": 2000.0, "p90": 3000.0, "buckets": {}},
            "transition_types": [{"value": "unknown", "confidence": 0.0,
                                  "source": "ffmpeg", "detection_method": "not-implemented-m3.2"}],
            "camera_moves": [{"value": "unknown", "confidence": 0.0,
                              "source": "ffmpeg", "detection_method": "not-implemented-m3.2"}],
            "pace_density": {"cuts_per_min": 1.0, "segment_density": 2.0},
            "color_continuity": {"status": "not_started"},
        },
        "summary": "t",
    }
    for key, value in overrides.items():
        parts = key.split(".")
        target = rhythm
        for p in parts[:-1]:
            target = target[p]
        target[parts[-1]] = value
    return rhythm


def run_eval_proc(suite, pred, milestone):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(pred, f)
        pred_path = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(suite, f)
        suite_path = f.name
    try:
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "evaluate_video.py"),
             "--ground-truth", suite_path, "--prediction", pred_path,
             "--milestone", milestone],
            capture_output=True, text=True)
    finally:
        os.unlink(pred_path)
        os.unlink(suite_path)


def run_validate(rhythm):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(rhythm, f)
        path = f.name
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "analyze_video.py"), "validate", path],
            capture_output=True, text=True)
        report = json.loads(proc.stdout)
        return report["ok"], report["errors"]
    finally:
        os.unlink(path)


class TestEvaluatorMissingFields(unittest.TestCase):
    """验收器：缺失 shot_count / avg_shot_ms / segments 必须失败。"""

    @classmethod
    def setUpClass(cls):
        cls.suite = load_suite()

    def test_missing_shot_count_fails(self):
        pred = build_prediction(self.suite)
        for item in pred.values():
            item["rhythm"]["params"].pop("shot_count")
        proc = run_eval_proc(self.suite, pred, "M3.1")
        report = json.loads(proc.stdout)
        self.assertEqual(report["summary"]["passed"], 0)
        self.assertIn("shot_count", report["summary"]["missing_fields"])

    def test_missing_avg_shot_ms_fails(self):
        pred = build_prediction(self.suite)
        for item in pred.values():
            item["rhythm"]["params"].pop("avg_shot_ms")
        proc = run_eval_proc(self.suite, pred, "M3.1")
        report = json.loads(proc.stdout)
        self.assertEqual(report["summary"]["passed"], 0)
        self.assertIn("avg_shot_ms", report["summary"]["missing_fields"])

    def test_m31_missing_segments_fails(self):
        pred = build_prediction(self.suite)
        for item in pred.values():
            item["probe"].pop("segments")
        proc = run_eval_proc(self.suite, pred, "M3.1")
        report = json.loads(proc.stdout)
        self.assertEqual(report["summary"]["passed"], 0)
        self.assertTrue(any(not r["segment_integrity_ok"] for r in report["results"]))

    def test_m31_with_segments_passes(self):
        pred = build_prediction(self.suite)
        proc = run_eval_proc(self.suite, pred, "M3.1")
        report = json.loads(proc.stdout)
        self.assertEqual(report["summary"]["passed"], 3)


class TestNaNInfinity(unittest.TestCase):
    """validate_segments 与 validate 必须拒绝 NaN / Infinity。"""

    def test_validate_segments_rejects_nan_duration(self):
        segs = [{"index": 1, "start_ms": 0.0, "duration_ms": float("nan")}]
        ok, errors = av.validate_segments(segs, 1000.0)
        self.assertFalse(ok)
        self.assertTrue(any("非有限" in e for e in errors))

    def test_validate_segments_rejects_inf_duration(self):
        segs = [{"index": 1, "start_ms": 0.0, "duration_ms": float("inf")}]
        ok, errors = av.validate_segments(segs, 1000.0)
        self.assertFalse(ok)
        self.assertTrue(any("非有限" in e for e in errors))

    def test_validate_segments_rejects_nan_start(self):
        segs = [{"index": 1, "start_ms": float("nan"), "duration_ms": 1000.0}]
        ok, errors = av.validate_segments(segs, 1000.0)
        self.assertFalse(ok)

    def test_validate_segments_rejects_nan_duration_ms(self):
        segs = [{"index": 1, "start_ms": 0.0, "duration_ms": 1000.0}]
        ok, errors = av.validate_segments(segs, float("nan"))
        self.assertFalse(ok)

    def test_validate_rejects_nan_avg_shot_ms(self):
        ok, errors = run_validate(full_rhythm(**{"params.avg_shot_ms": float("nan")}))
        self.assertFalse(ok)
        self.assertTrue(any("有限" in e for e in errors))

    def test_validate_rejects_inf_confidence(self):
        ok, errors = run_validate(full_rhythm(**{"params.transition_types": [
            {"value": "x", "confidence": float("inf"), "source": "s", "detection_method": "d"}]}))
        self.assertFalse(ok)
        self.assertTrue(any("有限" in e for e in errors))

    def test_validate_rejects_nan_percentile(self):
        ok, errors = run_validate(full_rhythm(**{"params.shot_length_distribution": {
            "p10": float("nan"), "p50": 2000.0, "p90": 3000.0, "buckets": {}}}))
        self.assertFalse(ok)

    def test_validate_accepts_finite_values(self):
        ok, errors = run_validate(full_rhythm())
        self.assertTrue(ok, errors)


class TestFfmpegAdapterRobustness(unittest.TestCase):
    """malformed ffprobe JSON / 非法帧率 / 阈值单位。"""

    def test_malformed_ffprobe_json_structured_error(self):
        fake = mock.MagicMock(stdout="{not json at all")
        with mock.patch.object(av.shutil, "which", return_value="/usr/bin/ffprobe"):
            with mock.patch.object(av.subprocess, "run", return_value=fake):
                with self.assertRaises(RuntimeError) as ctx:
                    av.FfmpegAdapter().probe("/tmp/x.mp4")
                self.assertIn("无法解析", str(ctx.exception))

    def test_invalid_fps_string_structured_error(self):
        payload = json.dumps({
            "streams": [{"codec_type": "video", "duration": "10",
                         "avg_frame_rate": "abc/def", "width": 1, "height": 1,
                         "codec_name": "h264"}],
            "format": {"duration": "10", "format_name": "mp4"}})
        fake = mock.MagicMock(stdout=payload)
        with mock.patch.object(av.shutil, "which", return_value="/usr/bin/ffprobe"):
            with mock.patch.object(av.subprocess, "run", return_value=fake):
                with self.assertRaises(RuntimeError) as ctx:
                    av.FfmpegAdapter().probe("/tmp/x.mp4")
                self.assertIn("非法帧率", str(ctx.exception))

    def test_invalid_scene_threshold_rejected(self):
        with self.assertRaises(RuntimeError):
            av.FfmpegAdapter(scene_threshold=1.5)
        with self.assertRaises(RuntimeError):
            av.FfmpegAdapter(scene_threshold=-0.01)

    def test_scene_threshold_boundaries_valid(self):
        av.FfmpegAdapter(scene_threshold=0.0)
        av.FfmpegAdapter(scene_threshold=1.0)
        av.FfmpegAdapter(scene_threshold=0.30)

    def test_threshold_unit_constant(self):
        self.assertEqual(av.FfmpegAdapter.SCENE_THRESHOLD_UNIT, "normalized-0-1")
        self.assertEqual(av.FfmpegAdapter.FFMPEG_SCDET_THRESHOLD_UNIT, "0-100")

    def test_threshold_maps_to_ffmpeg_scale(self):
        self.assertEqual(av.FfmpegAdapter(scene_threshold=0.30).ffmpeg_scene_threshold, 30.0)


class TestM33Gate(unittest.TestCase):
    """M3.3 无 color_continuity ground truth 时必须拒绝执行。"""

    @classmethod
    def setUpClass(cls):
        cls.suite = load_suite()

    def test_m33_blocked_without_ground_truth(self):
        pred = build_prediction(self.suite)
        proc = run_eval_proc(self.suite, pred, "M3.3")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("不允许", proc.stdout)
        self.assertIn("color_continuity", proc.stdout)

    def test_suite_marks_m33_not_ready(self):
        m33 = self.suite.get("acceptance_by_milestone", {}).get("M3.3", {})
        self.assertIs(m33.get("ready"), False)


if __name__ == "__main__":
    unittest.main()
