#!/usr/bin/env python3
"""M3.1.1 契约修正测试。不依赖真实 ffmpeg（当前环境未安装）。

覆盖：
- missing ffmpeg/ffprobe 错误信息
- ffprobe 失败、无视频流、零时长
- scdet 输出解析（标准/冒号/空/重复/越界）
- segment 完整性（零时长/不连续拒绝）
- overall_pace 派生规则
- Mock 与 Ffmpeg 的 cuts_per_min 定义一致
- mock 输出包含 overall_pace / coverage
- M3.1 验收不因 M3.2 unknown 字段失败；M3.2 验收会失败
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SCRIPT_DIR, "scripts")
sys.path.insert(0, SCRIPTS)

import analyze_video as av  # noqa: E402


class TestScdetParsing(unittest.TestCase):
    def test_parse_standard_equals(self):
        text = "frame:1 pts:1 pts_time:0.04 lavfi.scd.time=1.250\n... lavfi.scd.time=3.750"
        cuts, warnings = av.parse_scdet_output(text, 10.0)
        self.assertEqual(cuts, [1.25, 3.75])
        self.assertEqual(warnings, [])

    def test_parse_colon_format(self):
        cuts, warnings = av.parse_scdet_output("lavfi.scd.time: 2.500", 10.0)
        self.assertEqual(cuts, [2.5])
        self.assertEqual(warnings, [])

    def test_parse_empty_output(self):
        cuts, warnings = av.parse_scdet_output("", 10.0)
        self.assertEqual(cuts, [])
        self.assertTrue(any("lavfi.scd" in w for w in warnings))

    def test_parse_no_timestamps(self):
        cuts, warnings = av.parse_scdet_output("frame:1 lavfi.scd.time unavailable", 10.0)
        self.assertEqual(cuts, [])
        self.assertTrue(any("未解析到任何时间戳" in w for w in warnings))

    def test_parse_duplicate_and_boundary(self):
        text = ("lavfi.scd.time=0.000\n"
                "lavfi.scd.time=1.000\n"
                "lavfi.scd.time=1.000\n"
                "lavfi.scd.time=9.999\n"
                "lavfi.scd.time=10.500\n")
        cuts, warnings = av.parse_scdet_output(text, 10.0)
        self.assertEqual(cuts, [1.0, 9.999])
        self.assertTrue(any("过滤" in w for w in warnings))


class TestSegmentIntegrity(unittest.TestCase):
    def test_validate_segments_ok(self):
        segments = [
            {"index": 1, "start_ms": 0, "duration_ms": 1000},
            {"index": 2, "start_ms": 1000, "duration_ms": 2000},
        ]
        ok, errors = av.validate_segments(segments, 3000)
        self.assertTrue(ok, errors)

    def test_validate_segments_zero_duration_rejected(self):
        segments = [
            {"index": 1, "start_ms": 0, "duration_ms": 0},
            {"index": 2, "start_ms": 0, "duration_ms": 1000},
        ]
        ok, errors = av.validate_segments(segments, 1000)
        self.assertFalse(ok)
        self.assertTrue(any("零/负时长" in e for e in errors))

    def test_validate_segments_discontinuous_rejected(self):
        segments = [
            {"index": 1, "start_ms": 0, "duration_ms": 1000},
            {"index": 2, "start_ms": 2500, "duration_ms": 500},
        ]
        ok, errors = av.validate_segments(segments, 1500)
        self.assertFalse(ok)


class TestOverallPace(unittest.TestCase):
    def test_derive_rules(self):
        self.assertEqual(av.derive_overall_pace(780), "fast")
        self.assertEqual(av.derive_overall_pace(1199), "fast")
        self.assertEqual(av.derive_overall_pace(1200), "medium")
        self.assertEqual(av.derive_overall_pace(2450), "medium")
        self.assertEqual(av.derive_overall_pace(2999), "medium")
        self.assertEqual(av.derive_overall_pace(3000), "slow")
        self.assertEqual(av.derive_overall_pace(9200), "slow")


class TestCutsPerMinConsistency(unittest.TestCase):
    def test_mock_ffmpeg_same_definition(self):
        probe = {
            "adapter": "mock", "duration_ms": 60000, "shot_count": 6, "seed": 42,
            "segments": [{"index": i + 1, "start_ms": i * 10000, "duration_ms": 10000} for i in range(6)],
        }
        mock_rhythm = av.build_rhythm_params(probe, adapter_name="mock")
        segment_result = {
            "probe": {"adapter": "ffmpeg", "duration_ms": 60000, "width": 1920,
                      "height": 1080, "fps": 30.0, "codec": "h264", "format": "mp4"},
            "segments": probe["segments"],
            "cut_times_s": [10.0, 20.0, 30.0, 40.0, 50.0],
            "warnings": [],
        }
        ffmpeg_rhythm = av.build_segment_rhythm(segment_result)
        self.assertEqual(
            mock_rhythm["params"]["pace_density"]["cuts_per_min"],
            ffmpeg_rhythm["params"]["pace_density"]["cuts_per_min"],
        )
        # 6 段 / 1 分钟 -> 5 个切点/分钟
        self.assertEqual(mock_rhythm["params"]["pace_density"]["cuts_per_min"], 5.0)
        self.assertEqual(mock_rhythm["params"]["pace_density"]["segment_density"], 6.0)


class TestFfmpegAdapterErrors(unittest.TestCase):
    def test_missing_tools_message(self):
        with mock.patch.object(av.shutil, "which", return_value=None):
            adapter = av.FfmpegAdapter()
            with self.assertRaises(RuntimeError) as ctx:
                adapter.probe("/tmp/x.mp4")
            msg = str(ctx.exception)
            self.assertIn("ffprobe", msg)
            self.assertIn("ffmpeg", msg)

    def test_ffprobe_failure_raises(self):
        with mock.patch.object(av.shutil, "which", return_value="/usr/bin/ffprobe"):
            with mock.patch.object(av.subprocess, "run",
                                   side_effect=av.subprocess.CalledProcessError(1, "ffprobe")):
                adapter = av.FfmpegAdapter()
                with self.assertRaises(RuntimeError) as ctx:
                    adapter.probe("/tmp/x.mp4")
                self.assertIn("视频分析命令失败", str(ctx.exception))

    def test_zero_duration_rejected(self):
        ffprobe_json = json.dumps({
            "streams": [{"codec_type": "video", "duration": "0", "avg_frame_rate": "30/1",
                         "width": 100, "height": 100, "codec_name": "h264"}],
            "format": {"duration": "0", "format_name": "mp4"},
        })
        fake_result = mock.MagicMock(stdout=ffprobe_json)
        with mock.patch.object(av.shutil, "which", return_value="/usr/bin/ffprobe"):
            with mock.patch.object(av.subprocess, "run", return_value=fake_result):
                adapter = av.FfmpegAdapter()
                with self.assertRaises(RuntimeError) as ctx:
                    adapter.probe("/tmp/x.mp4")
                self.assertIn("无效的视频时长", str(ctx.exception))

    def test_no_video_stream_rejected(self):
        ffprobe_json = json.dumps({
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "5", "format_name": "mp4"},
        })
        fake_result = mock.MagicMock(stdout=ffprobe_json)
        with mock.patch.object(av.shutil, "which", return_value="/usr/bin/ffprobe"):
            with mock.patch.object(av.subprocess, "run", return_value=fake_result):
                adapter = av.FfmpegAdapter()
                with self.assertRaises(RuntimeError) as ctx:
                    adapter.probe("/tmp/x.mp4")
                self.assertIn("未找到视频流", str(ctx.exception))


class TestMockOutput(unittest.TestCase):
    def test_mock_output_has_overall_pace_and_coverage(self):
        out = run_cli(["mock", "m31-contract-seed"])
        rhythm = out["rhythm"]
        self.assertIn("overall_pace", rhythm)
        self.assertIn(rhythm["overall_pace"], ("fast", "medium", "slow"))
        self.assertIn("coverage", rhythm)
        self.assertGreater(rhythm["params"]["shot_count"], 0)
        self.assertGreater(rhythm["params"]["avg_shot_ms"], 0)


class TestMilestoneAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        suite_path = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)),
                                  "configs", "video-test-suite.json")
        cls.suite = json.load(open(suite_path))
        cls.pred = {}
        for sample in cls.suite["samples"]:
            gt = sample["ground_truth"]
            avg = gt["avg_shot_ms"]
            count = gt["shot_count"]
            cls.pred[sample["id"]] = {
                "probe": {
                    "duration_ms": avg * count,
                    "segments": [
                        {"index": i + 1, "start_ms": round(i * avg), "duration_ms": round(avg)}
                        for i in range(count)
                    ],
                },
                "rhythm": {
                    "status": "partial",
                    "overall_pace": av.derive_overall_pace(avg),
                    "params": {
                        "shot_count": count,
                        "avg_shot_ms": avg,
                        "shot_length_distribution": {
                            "p10": gt["shot_length_ms"]["p10"],
                            "p50": gt["shot_length_ms"]["p50"],
                            "p90": gt["shot_length_ms"]["p90"],
                            "buckets": {"0-1s": 0, "1-2s": 0, "2-4s": 0, "4s+": 0},
                        },
                        "transition_types": [{"value": "unknown", "confidence": 0.0,
                                              "source": "ffmpeg", "detection_method": "not-implemented-m3.2"}],
                        "camera_moves": [{"value": "unknown", "confidence": 0.0,
                                          "source": "ffmpeg", "detection_method": "not-implemented-m3.2"}],
                        "pace_density": {"cuts_per_min": 1.0, "segment_density": 1.0},
                        "color_continuity": {"status": "not_started"},
                    },
                    "summary": "m31 test",
                },
            }

    def _write(self, payload):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(payload, f)
        f.close()
        return f.name

    def test_m31_acceptance_passes_with_unknown_m32(self):
        pred_path = self._write(self.pred)
        suite_path = self._write(self.suite)
        try:
            report = run_eval(suite_path, pred_path, milestone="M3.1")
            self.assertEqual(report["summary"]["passed"], report["summary"]["samples"])
            self.assertEqual(report["summary"]["samples"], 3)
        finally:
            os.unlink(pred_path)
            os.unlink(suite_path)

    def test_m32_acceptance_fails_with_unknown_transition(self):
        pred_path = self._write(self.pred)
        suite_path = self._write(self.suite)
        try:
            report = run_eval(suite_path, pred_path, milestone="M3.2")
            self.assertLess(report["summary"]["passed"], report["summary"]["samples"])
        finally:
            os.unlink(pred_path)
            os.unlink(suite_path)


def run_eval(suite_path, pred_path, milestone):
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "evaluate_video.py"),
         "--ground-truth", suite_path, "--prediction", pred_path, "--milestone", milestone],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"evaluate_video 失败: {proc.stderr}")
    return json.loads(proc.stdout)


def run_cli(args):
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "analyze_video.py")] + args,
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"analyze_video 失败: {proc.stderr}")
    return json.loads(proc.stdout)


if __name__ == "__main__":
    unittest.main()
