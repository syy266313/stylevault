#!/usr/bin/env python3
"""StyleVault 视频分析验收脚本（M3.0.5）

比较未来 FfmpegAdapter 输出与 ground truth 的误差：
- shot_count
- avg_shot_ms
- transition_types
- camera_moves
- overall_pace
"""
import argparse
import json
import os
import sys


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


def main():
    ap = argparse.ArgumentParser(description="StyleVault video acceptance evaluator")
    ap.add_argument("--ground-truth", required=True, help="video-test-suite.json")
    ap.add_argument("--prediction", required=True, help="adapter output JSON")
    ap.add_argument("--sample-id", help="仅评估某个样本 id")
    ap.add_argument("--report", help="输出报告 JSON 路径")
    args = ap.parse_args()

    suite = load_json(args.ground_truth)
    pred = load_json(args.prediction)
    samples = suite.get("samples", [])
    if args.sample_id:
        samples = [s for s in samples if s.get("id") == args.sample_id]

    results = []
    for s in samples:
        sid = s["id"]
        p = pred.get(sid, pred) if isinstance(pred, dict) else {}
        r = evaluate_sample(s["ground_truth"], p)
        thresh = suite.get("acceptance", {})
        passed = (
            (r["shot_count_error"] is None or r["shot_count_error"] <= thresh.get("shot_count_abs_error", 1))
            and (r["avg_shot_ms_mae_ratio"] is None or r["avg_shot_ms_mae_ratio"] <= thresh.get("avg_shot_ms_mae_ratio", 0.15))
            and r["transition_jaccard"] >= thresh.get("transition_jaccard_min", 0.5)
            and r["camera_moves_jaccard"] >= thresh.get("camera_moves_jaccard_min", 0.5)
            and r["overall_pace_match"] == thresh.get("overall_pace_match", True)
        )
        r.update({"sample_id": sid, "title": s.get("title"), "passed": passed})
        results.append(r)

    summary = {
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

    report = {"suite": os.path.basename(args.ground_truth), "summary": summary, "results": results}
    if args.report:
        with open(args.report, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
