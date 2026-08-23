#!/usr/bin/env python3
"""Validate and summarize the report-only M3.3.1 benchmark manifest."""
import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SHA1_RE = re.compile(r"^[a-f0-9]{40}$")
ITEM_RE = re.compile(r"^sv_[0-9]{8}_[a-z0-9]{8}$")
SAMPLE_RE = re.compile(r"^real_[A-Za-z0-9_-]+$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
MEDIA_KEY_RE = re.compile(r"(?:^|_)(?:path|file|media|source_path|source_file|filename|url|uri|binary|bytes|content)(?:$|_)", re.I)
SECRET_KEY_RE = re.compile(r"(?:token|password|secret|credential|api[_-]?key)", re.I)
MEDIA_EXT_RE = re.compile(r"\.(?:mp4|mov|m4v|avi|mkv|webm|png|jpg|jpeg|heic|wav|mp3|m4a)$", re.I)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def finite_positive(value, integer=False):
    if integer and (not isinstance(value, int) or isinstance(value, bool)):
        return False
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return math.isfinite(value) and value > 0


def iso_or_none(value):
    return value is None or (isinstance(value, str) and bool(ISO_RE.fullmatch(value)))


def scan_for_forbidden_content(value, key=""):
    errors = []
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            name = str(child_key)
            lowered = name.casefold()
            if SECRET_KEY_RE.search(name):
                errors.append(f"forbidden credential field: {name}")
            if MEDIA_KEY_RE.search(name):
                errors.append(f"forbidden media/path field: {name}")
            errors.extend(scan_for_forbidden_content(child_value, name))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(scan_for_forbidden_content(child, f"{key}[{index}]"))
    elif isinstance(value, str):
        if "://" in value or MEDIA_EXT_RE.search(value) or "-----BEGIN " in value:
            errors.append(f"forbidden media/credential content at {key}")
    return errors


def annotation_error(annotation, contract, sample_id):
    errors = []
    if annotation is None:
        return errors
    if not isinstance(annotation, dict):
        return [f"{sample_id}: annotations must be an object"]
    low, high = contract["confidence_range"]
    for field in ("transition_types", "camera_moves"):
        values = annotation.get(field, [])
        if not isinstance(values, list):
            errors.append(f"{sample_id}: annotations.{field} must be a list")
            continue
        allowed = set(contract[field])
        for index, event in enumerate(values):
            if not isinstance(event, dict):
                errors.append(f"{sample_id}: annotations.{field}[{index}] must be an object")
                continue
            if event.get("value") not in allowed:
                errors.append(f"{sample_id}: invalid {field} label {event.get('value')!r}")
            errors.extend(validate_event_times(event, sample_id, field, index))
            errors.extend(validate_confidence(event.get("confidence"), low, high, f"{sample_id}: {field}[{index}].confidence"))
    color = annotation.get("color_continuity")
    if color is not None:
        if not isinstance(color, dict) or color.get("value") not in set(contract["color_continuity"]):
            errors.append(f"{sample_id}: invalid color_continuity label")
        elif "confidence" in color:
            errors.extend(validate_confidence(color["confidence"], low, high, f"{sample_id}: color_continuity.confidence"))
    boundaries = annotation.get("shot_boundaries", [])
    if not isinstance(boundaries, list):
        errors.append(f"{sample_id}: shot_boundaries must be a list")
    else:
        previous = -1
        for index, boundary in enumerate(boundaries):
            value = boundary.get("time_ms") if isinstance(boundary, dict) else boundary
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0 or value <= previous:
                errors.append(f"{sample_id}: invalid or unordered shot boundary at index {index}")
            previous = value if isinstance(value, (int, float)) else previous
            if isinstance(boundary, dict) and "confidence" in boundary:
                errors.extend(validate_confidence(boundary["confidence"], low, high, f"{sample_id}: shot_boundaries[{index}].confidence"))
    for field in ("annotator_id", "annotated_at"):
        if contract.get(f"require_{field.replace('_id', '_code')}", False) and not annotation.get(field):
            errors.append(f"{sample_id}: missing annotations.{field}")
    if contract.get("require_annotator_code") and not isinstance(annotation.get("annotator_id"), str):
        errors.append(f"{sample_id}: annotations.annotator_id is required")
    if contract.get("require_annotated_at") and not ISO_RE.fullmatch(str(annotation.get("annotated_at", ""))):
        errors.append(f"{sample_id}: annotations.annotated_at is invalid")
    return errors


def validate_event_times(event, sample_id, field, index):
    errors = []
    if "time_ms" in event and (not isinstance(event["time_ms"], (int, float)) or event["time_ms"] < 0 or not math.isfinite(event["time_ms"])):
        errors.append(f"{sample_id}: invalid {field}[{index}].time_ms")
    if "window_ms" in event:
        window = event["window_ms"]
        if not isinstance(window, list) or len(window) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in window) or window[1] < window[0]:
            errors.append(f"{sample_id}: invalid {field}[{index}].window_ms")
    return errors


def validate_confidence(value, low, high, label):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
        return [f"{label} outside [{low}, {high}]"]
    return []


def validate_sample(sample, config, seen_ids, seen_items, seen_sha):
    errors = []
    if not isinstance(sample, dict):
        return ["sample must be an object"]
    required = ("sample_id", "item_id", "source_sha1", "source_kind", "source_origin", "duration_ms", "width", "height", "fps", "codec", "capture_time", "split", "annotation_status", "privacy_status")
    missing = [field for field in required if field not in sample]
    errors.extend(f"sample missing {field}" for field in missing)
    sample_id = sample.get("sample_id", "<unknown>")
    if sample_id in seen_ids:
        errors.append(f"duplicate sample_id: {sample_id}")
    seen_ids.add(sample_id)
    item_id = sample.get("item_id")
    if item_id in seen_items:
        errors.append(f"duplicate item_id: {item_id}")
    seen_items.add(item_id)
    sha = sample.get("source_sha1")
    if not isinstance(sha, str) or not SHA1_RE.fullmatch(sha):
        errors.append(f"{sample_id}: source_sha1 must be lowercase SHA-1")
    elif sha in seen_sha:
        previous_split = seen_sha[sha]
        errors.append(f"{sample_id}: duplicate source_sha1; already used in split {previous_split}")
    else:
        seen_sha[sha] = sample.get("split")
    if not isinstance(sample_id, str) or not SAMPLE_RE.fullmatch(sample_id):
        errors.append(f"invalid sample_id: {sample_id!r}")
    if not isinstance(item_id, str) or not ITEM_RE.fullmatch(item_id):
        errors.append(f"{sample_id}: invalid item_id")
    if sample.get("source_kind") != "user_video":
        errors.append(f"{sample_id}: source_kind must be user_video")
    if sample.get("source_origin") not in {"photos", "attachment", "import"}:
        errors.append(f"{sample_id}: invalid source_origin")
    for field in ("duration_ms", "width", "height"):
        if not finite_positive(sample.get(field), integer=True):
            errors.append(f"{sample_id}: {field} must be a positive integer")
    if not finite_positive(sample.get("fps")):
        errors.append(f"{sample_id}: fps must be positive and finite")
    if not isinstance(sample.get("codec"), str) or not sample["codec"].strip():
        errors.append(f"{sample_id}: codec must be non-empty")
    if not iso_or_none(sample.get("capture_time")):
        errors.append(f"{sample_id}: capture_time must be ISO-8601 or null")
    if sample.get("split") not in set(config["allowed_splits"]):
        errors.append(f"{sample_id}: invalid split")
    if sample.get("annotation_status") not in set(config["annotation_contract"]["status_values"]):
        errors.append(f"{sample_id}: invalid annotation_status")
    if sample.get("privacy_status") not in set(config["privacy"]["allowed_statuses"]):
        errors.append(f"{sample_id}: invalid privacy_status")
    errors.extend(scan_for_forbidden_content(sample))
    errors.extend(annotation_error(sample.get("annotations"), config["annotation_contract"], sample_id))
    return sorted(set(errors))


def validate_manifest(manifest, config):
    errors = []
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    required = {"version", "milestone", "purpose", "acceptance_role", "samples"}
    errors.extend(f"manifest missing {key}" for key in sorted(required - set(manifest)))
    for key, expected in (("version", config["version"]), ("milestone", config["milestone"]), ("acceptance_role", "benchmark_report_only")):
        if manifest.get(key) != expected:
            errors.append(f"manifest {key} mismatch")
    if not isinstance(manifest.get("purpose"), str) or not manifest.get("purpose"):
        errors.append("manifest purpose must be non-empty")
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        return errors + ["manifest samples must be a list"]
    seen_ids, seen_items, seen_sha = set(), set(), {}
    for sample in samples:
        errors.extend(validate_sample(sample, config, seen_ids, seen_items, seen_sha))
    return sorted(set(errors))


def build_report(manifest, config, validation_errors=None):
    samples = manifest.get("samples", []) if isinstance(manifest, dict) and isinstance(manifest.get("samples", []), list) else []
    valid = not validation_errors
    split = Counter(sample.get("split") for sample in samples if isinstance(sample, dict))
    privacy = Counter(sample.get("privacy_status") for sample in samples if isinstance(sample, dict))
    annotation = Counter(sample.get("annotation_status") for sample in samples if isinstance(sample, dict))
    eligible = sum(1 for sample in samples if isinstance(sample, dict) and sample.get("privacy_status") == "approved_local_only" and sample.get("annotation_status") == "complete")
    excluded = len(samples) - eligible
    metrics = {"available": False, "reason": "real benchmark metrics unavailable: manifest is empty" if not samples else "detector evaluation is not implemented in this report scaffold"}
    return {"ok": valid, "benchmark": "M3.3.1", "acceptance_role": "benchmark_report_only", "total_samples": len(samples), "eligible_samples": eligible, "excluded_samples": excluded, "counts": {"by_split": dict(split), "by_privacy_status": dict(privacy), "by_annotation_status": dict(annotation)}, "metrics": metrics, "validation_errors": validation_errors or []}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate M3.3.1 benchmark manifest and emit report-only scaffold")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[3] / "configs" / "video-m3.3.1-benchmark.json"))
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        config = load_json(args.config)
        manifest = load_json(args.manifest) if args.manifest else config
        errors = validate_manifest(manifest, config)
        report = build_report(manifest, config, errors)
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0 if not errors else 1
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
