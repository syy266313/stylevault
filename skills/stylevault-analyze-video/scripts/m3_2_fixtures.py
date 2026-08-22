#!/usr/bin/env python3
"""M3.2 synthetic fixture generator and probe contract helpers.

This module defines videos from fixture specifications only. It does not
inspect or produce transition/camera predictions.
"""
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent.parent
CONFIG_PATH = REPO_ROOT / "configs" / "video-m3.2-fixtures.json"
import sys
sys.path.insert(0, str(SCRIPT_DIR))
from analyze_video import FfmpegAdapter  # noqa: E402


def load_fixture_specs(path=CONFIG_PATH):
    with open(path) as handle:
        payload = json.load(handle)
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) < 6:
        raise ValueError("M3.2 fixture 配置必须至少包含 6 个 fixture")
    required = {"static_hard_cut", "static_dissolve", "static_fade", "pan_horizontal", "zoom_in", "no_motion"}
    actual = {item.get("fixture_id") for item in fixtures}
    missing = required - actual
    if missing:
        raise ValueError(f"缺少 fixture: {sorted(missing)}")
    for item in fixtures:
        validate_fixture_spec(item)
    return payload


def validate_fixture_spec(spec):
    required = ["fixture_id", "generation_mode", "duration_s", "fps", "resolution",
                "shot_boundaries_ms", "transition_ground_truth", "camera_ground_truth",
                "ground_truth_source", "confidence_threshold", "tolerance"]
    missing = [key for key in required if key not in spec]
    if missing:
        raise ValueError(f"fixture {spec.get('fixture_id')} 缺少字段: {missing}")
    if spec["ground_truth_source"] != "synthetic_spec":
        raise ValueError(f"fixture {spec['fixture_id']} ground_truth_source 非 synthetic_spec")
    if not isinstance(spec["duration_s"], (int, float)) or not math.isfinite(spec["duration_s"]) or spec["duration_s"] <= 0:
        raise ValueError(f"fixture {spec['fixture_id']} duration_s 无效")
    if not isinstance(spec["fps"], int) or spec["fps"] <= 0:
        raise ValueError(f"fixture {spec['fixture_id']} fps 无效")
    if not isinstance(spec["resolution"], list) or len(spec["resolution"]) != 2 or any(int(x) <= 0 for x in spec["resolution"]):
        raise ValueError(f"fixture {spec['fixture_id']} resolution 无效")
    boundaries = spec["shot_boundaries_ms"]
    if not boundaries or boundaries[0] != 0 or boundaries[-1] != round(spec["duration_s"] * 1000):
        raise ValueError(f"fixture {spec['fixture_id']} shot_boundaries_ms 必须覆盖完整时长")
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in boundaries):
        raise ValueError(f"fixture {spec['fixture_id']} shot boundaries 必须为有限数")
    if any(b <= a for a, b in zip(boundaries, boundaries[1:])):
        raise ValueError(f"fixture {spec['fixture_id']} shot boundaries 必须严格递增")
    threshold = spec["confidence_threshold"]
    if not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError(f"fixture {spec['fixture_id']} confidence_threshold 无效")
    for key in ("transition_ground_truth", "camera_ground_truth"):
        for item in spec[key]:
            if not isinstance(item, dict) or "value" not in item or "confidence" not in item or "candidate" not in item:
                raise ValueError(f"fixture {spec['fixture_id']} {key} provenance 不完整")
            if not math.isfinite(item["confidence"]) or not 0 <= item["confidence"] <= 1:
                raise ValueError(f"fixture {spec['fixture_id']} {key} confidence 无效")


def _base_frame(size, color, seed):
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    margin = max(4, min(size) // 8)
    draw.rectangle((margin, margin, size[0] - margin, size[1] - margin), outline=(255, 255, 255), width=2)
    draw.ellipse((size[0] // 3, size[1] // 3, size[0] * 2 // 3, size[1] * 2 // 3), fill=(seed % 255, (seed * 3) % 255, (seed * 7) % 255))
    return image


def _frame_for_mode(spec, index, total_frames):
    size = tuple(spec["resolution"])
    seed = int(spec["seed"])
    mode = spec["generation_mode"]
    progress = index / max(1, total_frames - 1)
    if mode == "static_hard_cut":
        return _base_frame(size, "#be3f45" if progress < 0.5 else "#3068a8", seed)
    if mode == "static_dissolve":
        first = _base_frame(size, "#be3f45", seed)
        second = _base_frame(size, "#3068a8", seed + 1)
        alpha = min(1.0, max(0.0, (progress - 0.375) / 0.25))
        return Image.blend(first, second, alpha)
    if mode == "static_fade":
        base = _base_frame(size, "#be3f45", seed)
        alpha = 1.0 if progress < 0.375 or progress > 0.625 else abs(progress - 0.5) / 0.125
        return Image.blend(Image.new("RGB", size, "black"), base, alpha)
    if mode == "pan_horizontal":
        image = _base_frame((size[0] * 2, size[1]), "#3068a8", seed)
        draw = ImageDraw.Draw(image)
        draw.rectangle((size[0] // 2, 10, size[0] + size[0] // 2, size[1] - 10), fill="#be3f45")
        offset = int(progress * size[0])
        return image.crop((offset, 0, offset + size[0], size[1]))
    if mode == "zoom_in":
        canvas = _base_frame((size[0] * 2, size[1] * 2), "#3068a8", seed)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((size[0] // 2, size[1] // 2, size[0] * 3 // 2, size[1] * 3 // 2), fill="#be3f45")
        crop_w = int(size[0] * (1.7 - 0.7 * progress))
        crop_h = int(size[1] * (1.7 - 0.7 * progress))
        left = (canvas.width - crop_w) // 2
        top = (canvas.height - crop_h) // 2
        return canvas.crop((left, top, left + crop_w, top + crop_h)).resize(size)
    if mode == "no_motion":
        return _base_frame(size, "#be3f45", seed)
    raise ValueError(f"不支持的 generation_mode: {mode}")


def generate_fixture(spec, output_dir, adapter=None):
    validate_fixture_spec(spec)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = Path(tempfile.mkdtemp(prefix=f"{spec['fixture_id']}_", dir=output_dir))
    video_path = output_dir / f"{spec['fixture_id']}.mp4"
    total_frames = int(round(spec["duration_s"] * spec["fps"]))
    try:
        for index in range(total_frames):
            _frame_for_mode(spec, index, total_frames).save(frame_dir / f"frame_{index:06d}.png")
        (adapter or FfmpegAdapter()).encode_frame_sequence(str(frame_dir), str(video_path), spec["fps"])
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)
    return str(video_path)


def probe_fixture(spec, output_dir, adapter=None):
    video_path = generate_fixture(spec, output_dir, adapter=adapter)
    probe = (adapter or FfmpegAdapter()).probe(video_path)
    return {"fixture_id": spec["fixture_id"], "video_path": video_path, "probe": probe, "ground_truth": spec}
