#!/usr/bin/env python3
"""M3.3 color fixture and detector acceptance evaluator.

It generates independent synthetic fixtures, runs the FfmpegAdapter detector,
and compares detector metrics to synthetic-spec ground truth.
"""
import argparse
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze_video import FfmpegAdapter  # noqa: E402
from m3_3_color_fixtures import load_color_specs, probe_color_fixture  # noqa: E402


def compare_probe(spec, probe):
    tolerance = spec["tolerance"]
    errors = []
    expected_duration = spec["duration_s"] * 1000.0
    if abs(probe["duration_ms"] - expected_duration) > tolerance["duration_ms"]:
        errors.append(f"duration_ms mismatch: {probe['duration_ms']} vs {expected_duration}")
    width, height = spec["resolution"]
    if tolerance["resolution_exact"] and (probe.get("width"), probe.get("height")) != (width, height):
        errors.append(f"resolution mismatch: {(probe.get('width'), probe.get('height'))}")
    if abs(probe["fps"] - spec["fps"]) > tolerance["fps_abs"]:
        errors.append(f"fps mismatch: {probe['fps']} vs {spec['fps']}")
    return errors


def compare_detector(spec, result):
    observation = result["observation"]
    errors = []
    required = {"value", "confidence", "source", "detection_method", "candidate", "status", "metrics"}
    if not required.issubset(observation):
        errors.append("detector observation provenance incomplete")
    if observation.get("status") not in {"confirmed", "candidate"}:
        errors.append("invalid detector status")
    if not isinstance(observation.get("candidate"), bool):
        errors.append("detector candidate must be bool")
    for key in ("value", "source", "detection_method"):
        if not isinstance(observation.get(key), str) or not observation[key].strip():
            errors.append(f"detector {key} must be non-empty string")
    confidence = observation.get("confidence")
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        errors.append("detector confidence invalid")
    metrics = observation.get("metrics", {})
    sampling = result.get("sampling", {})
    if sampling.get("metrics_contract_version") != "m3.3.v1":
        errors.append("sampling metrics_contract_version mismatch")
    if sampling.get("include_start") is not True or sampling.get("include_end") is not True:
        errors.append("sampling include_start/include_end mismatch")
    if sampling.get("terminal_frame_policy") != "exact-duration":
        errors.append("sampling terminal_frame_policy mismatch")
    if metrics.get("metrics_contract_version") != "m3.3.v1":
        errors.append("metrics_contract_version mismatch")
    if metrics.get("interval_count") != len(metrics.get("deltas", [])):
        errors.append("interval_count mismatch")
    if metrics.get("terminal_frame_policy") != "exact-duration":
        errors.append("terminal_frame_policy mismatch")
    expected_count = spec.get("expected_interval_count")
    if expected_count is not None and metrics.get("interval_count") != expected_count:
        errors.append(f"interval_count outside spec: {metrics.get('interval_count')} vs {expected_count}")
    tolerance = spec["tolerance"]
    for key in ("mean_delta_e", "drift_rate", "stable_ratio"):
        actual = metrics.get(key)
        expected = spec[f"expected_{key}"]
        if not isinstance(actual, (int, float)) or not math.isfinite(actual):
            errors.append(f"detector {key} invalid")
        elif abs(actual - expected) > tolerance.get(key, 0):
            errors.append(f"detector {key} outside tolerance: {actual} vs {expected}")
    if metrics.get("dominant_shift") != spec["expected_dominant_shift"]:
        errors.append("detector dominant_shift mismatch")
    return errors


def compare_reference(spec, reference):
    errors = []
    tolerance = spec["tolerance"]
    for key in ("mean_delta_e", "drift_rate", "stable_ratio"):
        expected = spec[f"expected_{key}"]
        actual = reference[key]
        if key == "mean_delta_e" and spec["generation_mode"] != "stable_color":
            if actual <= 0:
                errors.append(f"{key} has no measurable color change")
        elif key == "drift_rate" and spec["generation_mode"] == "gradual_color_drift":
            if actual <= 0:
                errors.append(f"{key} has no measurable gradual drift")
        elif key == "stable_ratio" and spec["generation_mode"] == "stable_color":
            if actual < 1.0 - tolerance["stable_ratio"]:
                errors.append(f"{key} stable sequence is too low: {actual}")
        if expected != 0 and abs(actual - expected) > tolerance.get(key, 0):
            errors.append(f"{key} outside spec tolerance: {actual} vs {expected}")
    if reference["dominant_shift"] != spec["expected_dominant_shift"]:
        errors.append("dominant_shift does not match independent spec")
    if reference.get("metrics_contract_version") != "m3.3.v1":
        errors.append("reference metrics_contract_version mismatch")
    if reference.get("interval_count") != len(reference.get("deltas", [])):
        errors.append("reference interval_count mismatch")
    if reference.get("terminal_frame_policy") != "exact-duration":
        errors.append("reference terminal_frame_policy mismatch")
    if not reference["sample_times_s"] or len(reference["sample_times_s"]) != len(reference["colors"]):
        errors.append("sampling input contract is incomplete")
    return errors


def evaluate_config(config_path, output_dir=None):
    suite = load_color_specs(config_path)
    owned = output_dir is None
    output_dir = output_dir or tempfile.mkdtemp(prefix="stylevault_m33_color_")
    results = []
    try:
        for spec in suite["fixtures"]:
            adapter = FfmpegAdapter()
            result = probe_color_fixture(spec, output_dir, adapter=adapter)
            probe_errors = compare_probe(spec, result["probe"])
            reference_errors = compare_reference(spec, result["reference"])
            detection = adapter.analyze_color_continuity(result["video_path"], sampling_interval_s=spec["sampling_interval_s"])
            detector_errors = compare_detector(spec, detection)
            results.append({"fixture_id": spec["fixture_id"], "ok": not (probe_errors or reference_errors or detector_errors), "probe_errors": probe_errors, "reference_errors": reference_errors, "detector_errors": detector_errors, "reference": result["reference"], "detector": detection, "ground_truth_source": spec["ground_truth_source"]})
    finally:
        if owned:
            shutil.rmtree(output_dir, ignore_errors=True)
    return {"ok": all(item["ok"] for item in results), "fixtures": results}


def main():
    parser = argparse.ArgumentParser(description="Validate independent M3.3 color continuity fixtures")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[3] / "configs" / "video-m3.3-color-fixtures.json"))
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    try:
        report = evaluate_config(args.config, args.output_dir)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
