#!/usr/bin/env python3
"""M3.3 color-continuity fixture generator and independent reference metrics.

The reference metrics are derived from the color sequence specification, not
from any future detector output.
"""
import json
import math
import shutil
import tempfile
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent.parent
CONFIG_PATH = REPO_ROOT / "configs" / "video-m3.3-color-fixtures.json"
import sys
sys.path.insert(0, str(SCRIPT_DIR))
from analyze_video import FfmpegAdapter  # noqa: E402


def load_color_specs(path=CONFIG_PATH):
    with open(path) as handle:
        payload = json.load(handle)
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) < 5:
        raise ValueError("M3.3 color fixture 配置必须至少包含 5 个 fixture")
    required = {"stable_color", "gradual_color_drift", "abrupt_color_shift", "alternating_color", "fade_color_change"}
    actual = {item.get("fixture_id") for item in fixtures}
    missing = required - actual
    if missing:
        raise ValueError(f"缺少 color fixture: {sorted(missing)}")
    for spec in fixtures:
        validate_color_spec(spec)
    return payload


def validate_color_spec(spec):
    required = ["fixture_id", "generation_mode", "duration_s", "fps", "resolution", "sampling_interval_s", "expected_interval_count", "metrics_contract_version", "palette", "expected_mean_delta_e", "expected_drift_rate", "expected_stable_ratio", "expected_dominant_shift", "tolerance", "ground_truth_source"]
    missing = [key for key in required if key not in spec]
    if missing:
        raise ValueError(f"fixture {spec.get('fixture_id')} 缺少字段: {missing}")
    if spec["ground_truth_source"] != "synthetic_spec":
        raise ValueError(f"fixture {spec['fixture_id']} ground_truth_source 非 synthetic_spec")
    if spec["metrics_contract_version"] != "m3.3.v1":
        raise ValueError(f"fixture {spec['fixture_id']} metrics_contract_version 无效")
    if spec["expected_interval_count"] != round(spec["duration_s"] / spec["sampling_interval_s"]):
        raise ValueError(f"fixture {spec['fixture_id']} expected_interval_count 与 sampling 不一致")
    if not isinstance(spec["duration_s"], (int, float)) or not math.isfinite(spec["duration_s"]) or spec["duration_s"] <= 0:
        raise ValueError(f"fixture {spec['fixture_id']} duration_s 无效")
    if not isinstance(spec["fps"], int) or spec["fps"] <= 0:
        raise ValueError(f"fixture {spec['fixture_id']} fps 无效")
    if not isinstance(spec["resolution"], list) or len(spec["resolution"]) != 2 or any(int(x) <= 0 for x in spec["resolution"]):
        raise ValueError(f"fixture {spec['fixture_id']} resolution 无效")
    if not isinstance(spec["sampling_interval_s"], (int, float)) or not math.isfinite(spec["sampling_interval_s"]) or spec["sampling_interval_s"] <= 0:
        raise ValueError(f"fixture {spec['fixture_id']} sampling_interval_s 无效")
    if len(spec["palette"]) < 1 or any(len(color) != 3 or any(not isinstance(x, int) or not 0 <= x <= 255 for x in color) for color in spec["palette"]):
        raise ValueError(f"fixture {spec['fixture_id']} palette 无效")
    for key in ("expected_mean_delta_e", "expected_drift_rate", "expected_stable_ratio"):
        value = spec[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or (key == "expected_stable_ratio" and not 0 <= value <= 1):
            raise ValueError(f"fixture {spec['fixture_id']} {key} 无效")


def _srgb_channel(value):
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb):
    r, g, b = (_srgb_channel(value) for value in rgb)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 1.00000
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    def f(value):
        return value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(first, second):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))


def color_at(spec, time_s):
    mode = spec["generation_mode"]
    palette = spec["palette"]
    progress = min(1.0, max(0.0, time_s / spec["duration_s"]))
    if mode == "stable_color" or mode == "no_motion":
        return tuple(palette[0])
    if mode == "gradual_color_drift":
        a, b = palette[0], palette[1]
        return tuple(round(x + (y - x) * progress) for x, y in zip(a, b))
    if mode == "abrupt_color_shift":
        return tuple(palette[0] if progress < 0.5 else palette[1])
    if mode == "alternating_color":
        period = float(spec.get("period_s", 0.5))
        return tuple(palette[int(time_s / period) % len(palette)])
    if mode == "fade_color_change":
        first, second = palette[0], palette[1]
        center = float(spec.get("fade_center_s", spec["duration_s"] / 2))
        half = max(0.1, center / 2)
        if time_s <= center - half:
            return tuple(first)
        if time_s >= center + half:
            return tuple(second)
        blend = (time_s - (center - half)) / (2 * half)
        fade = min(1.0, blend * 2.0) if blend < 0.5 else min(1.0, (1.0 - blend) * 2.0)
        target = (0, 0, 0) if blend < 0.5 else tuple(second)
        base = first if blend < 0.5 else (0, 0, 0)
        return tuple(round(x + (y - x) * fade) for x, y in zip(base, target))
    raise ValueError(f"不支持的 generation_mode: {mode}")


def classify_dominant_shift(spec, labs, deltas, stable_ratio):
    first, last = labs[0], labs[-1]
    mean_delta = sum(deltas) / max(1, len(deltas))
    net = delta_e(first, last)
    if mean_delta <= 2.5 and stable_ratio >= 0.8:
        return "none"
    if mean_delta > 10 and 0.3 <= stable_ratio <= 0.7 and net <= 5:
        return "alternating"
    if stable_ratio >= 0.8 and max(deltas) > max(mean_delta * 8, 20):
        return "cool_to_warm_abrupt"
    luma = [0.2126 * value[0] + 0.7152 * value[1] + 0.0722 * value[2] for value in spec.get("_sample_colors", [])]
    if luma:
        trough = min(luma); index = luma.index(trough)
        if 0 < index < len(luma) - 1 and trough <= min(luma[0], luma[-1]) * 0.55:
            return "cool_to_warm_via_neutral"
    return "cool_to_warm" if (last[2] - first[2]) > 2 and (last[1] - first[1]) > 2 else "unknown"


def reference_metrics(spec):
    interval = spec["sampling_interval_s"]
    times = [i * interval for i in range(max(1, round(spec["duration_s"] / interval)) + 1)]
    labs = [rgb_to_lab(color_at(spec, time)) for time in times]
    deltas = [delta_e(a, b) for a, b in zip(labs, labs[1:])]
    mean_delta = sum(deltas) / max(1, len(deltas))
    stable_threshold = 2.5
    stable_ratio = sum(value <= stable_threshold for value in deltas) / max(1, len(deltas))
    total_drift = delta_e(labs[0], labs[-1])
    drift_rate = total_drift / max(times[-1] - times[0], 1e-9)
    colors = [color_at(spec, time) for time in times]
    spec_for_classification = dict(spec)
    spec_for_classification["_sample_colors"] = colors
    dominant_shift = classify_dominant_shift(spec_for_classification, labs, deltas, stable_ratio)
    return {"metrics_contract_version": "m3.3.v1", "mean_delta_e": mean_delta, "drift_rate": drift_rate, "stable_ratio": stable_ratio, "dominant_shift": dominant_shift, "deltas": deltas, "interval_count": len(deltas), "sample_times_s": times, "colors": colors, "sampling_interval_s": interval, "terminal_frame_policy": "exact-duration"}


def _frame_color(spec, index, total_frames):
    color = color_at(spec, index / float(spec["fps"]))
    return Image.new("RGB", tuple(spec["resolution"]), color=color)


def generate_color_fixture(spec, output_dir, adapter=None):
    validate_color_spec(spec)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = Path(tempfile.mkdtemp(prefix=f"{spec['fixture_id']}_", dir=output_dir))
    video_path = output_dir / f"{spec['fixture_id']}.mp4"
    # Include an explicit terminal frame so include_end=true is observable.
    total_frames = int(round(spec["duration_s"] * spec["fps"])) + 1
    try:
        for index in range(total_frames):
            _frame_color(spec, index, total_frames).save(frame_dir / f"frame_{index:06d}.png")
        (adapter or FfmpegAdapter()).encode_frame_sequence(str(frame_dir), str(video_path), spec["fps"])
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)
    return str(video_path)


def probe_color_fixture(spec, output_dir, adapter=None):
    adapter = adapter or FfmpegAdapter()
    video_path = generate_color_fixture(spec, output_dir, adapter=adapter)
    return {"fixture_id": spec["fixture_id"], "video_path": video_path, "probe": adapter.probe(video_path), "reference": reference_metrics(spec)}
