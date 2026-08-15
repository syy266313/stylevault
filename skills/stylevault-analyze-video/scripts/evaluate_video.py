#!/usr/bin/env python3
"""StyleVault 视频分析验收脚本（M3.0.5 + M3.1.1 契约修正）

按 milestone 分组验收：
- M3.1：probe / shot_count / avg_shot_ms / overall_pace / segment 完整性
- M3.2：追加 transition_types / camera_moves
- M3.3：追加 color_continuity（ground truth 就绪后启用）

M3.1 验收不因 M3.2 字段未实现（unknown 占位）而失败。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 复用 analyze_video 的纯函数（不触发 ffmpeg）
from analyze_video import validate_segments  # noqa: E402


def load_json(path):
    with open(path) as f:
        return json.load(f)


def as_values(items):
    vals = []
    for item in items or []:
        if isinstance(item, str):
            vals.append(item)
        elif isinstance(item, dict):
            if "value" in item:
                vals.append(item["value"])
            elif "tag" in item:
                vals.append(item["tag"])
    return sorted(set(vals))


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 1.0


def get_rhythm(pred):
    if not isinstance(pred, dict):
        return {}
    if "rhythm" in pred and isinstance(pred["rhythm"], dict):
        if "params" in pred["rhythm"]:
            return pred["rhythm"]["params"] | {"overall_pace": pred["rhythm"].get("overall_pace")}
        return pred["rhythm"]
    if "analysis" in pred and isinstance(pred["analysis"], dict):
        a = pred["analysis"]
        if isinstance(a.get("rhythm"), dict) and "params" in a["rhythm"]:
            return a["rhythm"]["params"] | {"overall_pace": a["rhythm"].get("overall_pace")}
    return pred


def get_segments(pred):
    """从 prediction 提取 segments（根级 / probe.segments / rhythm.probe.segments）。"""
    if isinstance(pred, dict):
        if isinstance(pred.get("segments"), list):
            return pred["segments"]
        probe = pred.get("probe") or (pred.get("rhythm") or {}).get("probe")
        if isinstance(probe, dict) and isinstance(probe.get("segments"), list):
            return probe["segments"]
    return None


def get_duration_ms(pred):
    if isinstance(pred, dict):
        probe = pred.get("probe") or (pred.get("rhythm") or {}).get("probe")
        if isinstance(probe, dict) and isinstance(probe.get("duration_ms"), (int, float)):
            return probe["duration_ms"]
    return None


def evaluate_sample(gt, pred):
    rhythm = get_rhythm(pred)
    gt_count = gt["shot_count"]
    gt_avg = gt["avg_shot_ms"]
    pred_count = rhythm.get("shot_count")
    pred_avg = rhythm.get("avg_shot_ms")
    trans_gt = as_values(gt.get("transition_types"))
    cam_gt = as_values(gt.get("camera_moves"))
    trans_pred = as_values(rhythm.get("transition_types"))
    cam_pred = as_values(rhythm.get("camera_moves"))

    shot_count_err = None if pred_count is None else abs(pred_count - gt_count)
    avg_shot_ms_err = None if pred_avg is None else abs(pred_avg - gt_avg)
    avg_shot_ms_mae_ratio = None if avg_shot_ms_err is None else avg_shot_ms_err / max(1, gt_avg)

    return {
        "shot_count_error": shot_count_err,
        "avg_shot_ms_error": avg_shot_ms_err,
        "avg_shot_ms_mae_ratio": avg_shot_ms_mae_ratio,
        "transition_jaccard": jaccard(trans_gt, trans_pred),
        "camera_moves_jaccard": jaccard(cam_gt, cam_pred),
        "overall_pace_match": rhythm.get("overall_pace") == gt.get("overall_pace"),
        "pred_overall_pace": rhythm.get("overall_pace"),
        "gt_overall_pace": gt.get("overall_pace"),
        "pred_transition_types": trans_pred,
        "pred_camera_moves": cam_pred,
    }


# 每个 milestone 必须通过的检查项
MILESTONE_REQUIRED = {
    "M3.1": ["shot_count", "avg_shot_ms", "overall_pace"],
    "M3.2": ["shot_count", "avg_shot_ms", "overall_pace", "transition", "camera_moves"],
    "M3.3": ["shot_count", "avg_shot_ms", "overall_pace", "transition", "camera_moves"],
}


def milestone_thresholds(suite, milestone):
    by_ms = suite.get("acceptance_by_milestone") or {}
    return by_ms.get(milestone) or suite.get("acceptance") or {}


def check_segment_integrity(pred):
    """M3.1 segment 完整性：prediction 携带 segments 时校验，缺失则跳过。"""
    segments = get_segments(pred)
    if segments is None:
        return True, ["skipped: prediction 无 segments 数据"]
    duration_ms = get_duration_ms(pred)
    if duration_ms is None:
        return False, ["缺少 probe.duration_ms，无法校验 segments"]
    return validate_segments(segments, duration_ms)


def main():
    ap = argparse.ArgumentParser(description="StyleVault video acceptance evaluator")
    ap.add_argument("--ground-truth", required=True, help="video-test-suite.json")
    ap.add_argument("--prediction", required=True, help="adapter output JSON")
    ap.add_argument("--sample-id", help="仅评估某个样本 id")
    ap.add_argument("--report", help="输出报告 JSON 路径")
    ap.add_argument("--milestone", choices=sorted(MILESTONE_REQUIRED), default="M3.1",
                    help="验收里程碑（默认 M3.1，不要求 M3.2 字段）")
    args = ap.parse_args()

    suite = load_json(args.ground_truth)
    pred = load_json(args.prediction)
    samples = suite.get("samples", [])
    if args.sample_id:
        samples = [s for s in samples if s.get("id") == args.sample_id]

    thresh = milestone_thresholds(suite, args.milestone)
    required = MILESTONE_REQUIRED[args.milestone]

    results = []
    for s in samples:
        sid = s["id"]
        p = pred.get(sid, pred) if isinstance(pred, dict) else {}
        r = evaluate_sample(s["ground_truth"], p)
        checks = {
            "shot_count": r["shot_count_error"] is None or r["shot_count_error"] <= thresh.get("shot_count_abs_error", 1),
            "avg_shot_ms": r["avg_shot_ms_mae_ratio"] is None or r["avg_shot_ms_mae_ratio"] <= thresh.get("avg_shot_ms_mae_ratio", 0.15),
            "overall_pace": r["overall_pace_match"] == thresh.get("overall_pace_match", True),
            "transition": r["transition_jaccard"] >= thresh.get("transition_jaccard_min", 0.5),
            "camera_moves": r["camera_moves_jaccard"] >= thresh.get("camera_moves_jaccard_min", 0.5),
        }
        seg_ok, seg_errors = (True, [])
        if args.milestone == "M3.1":
            seg_ok, seg_errors = check_segment_integrity(p)
        passed = all(checks[k] for k in required) and seg_ok
        r.update({
            "sample_id": sid,
            "title": s.get("title"),
            "passed": passed,
            "milestone": args.milestone,
            "required_checks": required,
            "checks": checks,
            "segment_integrity_ok": seg_ok,
            "segment_integrity_errors": seg_errors,
        })
        results.append(r)

    summary = {
        "milestone": args.milestone,
        "samples": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "shot_count_mae": None,
        "avg_shot_ms_mae_ratio_mean": None,
        "transition_jaccard_mean": None,
        "camera_moves_jaccard_mean": None,
    }
    sc = [r["shot_count_error"] for r in results if r["shot_count_error"] is not None]
    ar = [r["avg_shot_ms_mae_ratio"] for r in results if r["avg_shot_ms_mae_ratio"] is not None]
    tj = [r["transition_jaccard"] for r in results]
    cj = [r["camera_moves_jaccard"] for r in results]
    if sc:
        summary["shot_count_mae"] = sum(sc) / len(sc)
    if ar:
        summary["avg_shot_ms_mae_ratio_mean"] = sum(ar) / len(ar)
    if tj:
        summary["transition_jaccard_mean"] = sum(tj) / len(tj)
    if cj:
        summary["camera_moves_jaccard_mean"] = sum(cj) / len(cj)

    report = {
        "suite": os.path.basename(args.ground_truth),
        "milestone": args.milestone,
        "summary": summary,
        "results": results,
    }
    if args.report:
        with open(args.report, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
