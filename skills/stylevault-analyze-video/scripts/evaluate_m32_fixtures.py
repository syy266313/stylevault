#!/usr/bin/env python3
"""M3.2 synthetic fixture evaluator.

Fixture videos are generated from independent specs. Detection is run by the
FfmpegAdapter; this evaluator only compares predictions to those specs.
"""
import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze_video import FfmpegAdapter  # noqa: E402
from m3_2_fixtures import load_fixture_specs, probe_fixture  # noqa: E402


def compare_probe(spec, probe):
    tolerance = spec["tolerance"]
    expected_duration = spec["duration_s"] * 1000.0
    errors = []
    if abs(probe["duration_ms"] - expected_duration) > tolerance["duration_ms"]:
        errors.append(f"duration_ms {probe['duration_ms']} != {expected_duration} +/- {tolerance['duration_ms']}")
    width, height = spec["resolution"]
    if tolerance["resolution_exact"] and (probe.get("width"), probe.get("height")) != (width, height):
        errors.append(f"resolution {(probe.get('width'), probe.get('height'))} != {(width, height)}")
    if abs(probe["fps"] - spec["fps"]) > tolerance["fps_abs"]:
        errors.append(f"fps {probe['fps']} != {spec['fps']} +/- {tolerance['fps_abs']}")
    return errors


def _validate_observation(item):
    required = {"value", "confidence", "source", "detection_method", "candidate", "status"}
    if not isinstance(item, dict) or not required.issubset(item):
        return ["observation provenance incomplete"]
    confidence = item["confidence"]
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        return [f"invalid confidence: {confidence!r}"]
    if item["status"] == "confirmed" and item["candidate"]:
        return ["confirmed observation cannot be candidate"]
    if item["status"] == "candidate" and not item["candidate"]:
        return ["candidate observation must be marked candidate"]
    return []


def _values(items, threshold):
    return {item["value"] for item in items if item["value"] != "unknown" and item["confidence"] >= threshold and not item["candidate"]}


def compare_detection(spec, prediction, threshold=None):
    threshold = spec["confidence_threshold"] if threshold is None else threshold
    errors = []
    transition_pred = prediction.get("transition_types", [])
    camera_pred = prediction.get("camera_moves", [])
    for item in transition_pred + camera_pred:
        errors.extend(_validate_observation(item))
    transition_expected = {item["value"] for item in spec["transition_ground_truth"]}
    camera_expected = {item["value"] for item in spec["camera_ground_truth"]}
    transition_actual = _values(transition_pred, threshold)
    camera_actual = _values(camera_pred, threshold)
    if transition_expected != transition_actual:
        errors.append(f"transition mismatch: predicted={sorted(transition_actual)} ground_truth={sorted(transition_expected)}")
    if camera_expected != camera_actual:
        errors.append(f"camera mismatch: predicted={sorted(camera_actual)} ground_truth={sorted(camera_expected)}")
    return errors


def evaluate_config(config_path, output_dir=None, sampling_fps=None, confidence_threshold=None):
    suite = load_fixture_specs(config_path)
    owned_dir = output_dir is None
    output_dir = output_dir or tempfile.mkdtemp(prefix="stylevault_m32_fixtures_")
    adapter = FfmpegAdapter()
    results = []
    try:
        for spec in suite["fixtures"]:
            result = probe_fixture(spec, output_dir, adapter=adapter)
            probe_errors = compare_probe(spec, result["probe"])
            threshold = spec["confidence_threshold"] if confidence_threshold is None else confidence_threshold
            prediction = adapter.analyze_m32(
                result["video_path"],
                sampling_fps=spec["fps"] if sampling_fps is None else sampling_fps,
                confidence_threshold=threshold,
            )
            detection_errors = compare_detection(spec, prediction, threshold=threshold)
            results.append({
                "fixture_id": spec["fixture_id"],
                "ok": not (probe_errors or detection_errors),
                "probe_errors": probe_errors,
                "detection_errors": detection_errors,
                "prediction": {"transition_types": prediction["transition_types"], "camera_moves": prediction["camera_moves"]},
                "ground_truth": {"transition_types": spec["transition_ground_truth"], "camera_moves": spec["camera_ground_truth"]},
            })
    finally:
        if owned_dir:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)
    return {"ok": all(item["ok"] for item in results), "fixtures": results}


def main():
    parser = argparse.ArgumentParser(description="Validate M3.2 synthetic fixtures and frame detectors")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[3] / "configs" / "video-m3.2-fixtures.json"))
    parser.add_argument("--output-dir")
    parser.add_argument("--sampling-fps", type=float)
    parser.add_argument("--confidence-threshold", type=float)
    args = parser.parse_args()
    try:
        if args.confidence_threshold is not None and not 0 <= args.confidence_threshold <= 1:
            raise ValueError("confidence threshold must be in [0,1]")
        report = evaluate_config(args.config, args.output_dir, args.sampling_fps, args.confidence_threshold)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
