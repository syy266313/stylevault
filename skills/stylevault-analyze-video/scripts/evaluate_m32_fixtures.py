#!/usr/bin/env python3
"""Independent M3.2 fixture contract evaluator.

This evaluator validates synthetic specifications and real probe metadata only.
It intentionally does not evaluate transition_types or camera_moves.
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


def evaluate_config(config_path, output_dir=None):
    suite = load_fixture_specs(config_path)
    owned_dir = output_dir is None
    output_dir = output_dir or tempfile.mkdtemp(prefix="stylevault_m32_fixtures_")
    results = []
    try:
        for spec in suite["fixtures"]:
            result = probe_fixture(spec, output_dir)
            errors = compare_probe(spec, result["probe"])
            results.append({"fixture_id": spec["fixture_id"], "ok": not errors, "errors": errors})
    finally:
        if owned_dir:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)
    return {"ok": all(item["ok"] for item in results), "fixtures": results}


def main():
    parser = argparse.ArgumentParser(description="Validate M3.2 synthetic fixture generation and probe contract")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[3] / "configs" / "video-m3.2-fixtures.json"))
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
