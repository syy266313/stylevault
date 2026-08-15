#!/usr/bin/env python3
"""StyleVault analyze-video (M3.0 architecture only)

- 不直接依赖 ffmpeg；通过统一 adapter 接口抽象。
- mock 模式可验证 rhythm.params 和 style_dna 合并逻辑。
- 未来只需实现 FfmpegAdapter 即可接入真实视频分析。
"""
import argparse
import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def stable_seed(value: str) -> int:
    return int(sha1_text(value)[:8], 16)


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


class VideoAdapter:
    name = "base"

    def plan(self, source):
        raise NotImplementedError

    def probe(self, source):
        raise NotImplementedError

    def segment(self, source):
        raise NotImplementedError

    def representative_frames(self, source, segments):
        raise NotImplementedError


class FfmpegAdapter(VideoAdapter):
    """未来真实实现：只在这里接 ffmpeg。上层流程不直接依赖 ffmpeg。"""
    name = "ffmpeg"

    def plan(self, source):
        return {
            "adapter": self.name,
            "source": source,
            "steps": [
                "ffprobe 读取时长/帧率/分辨率",
                "scdet 或 scene threshold 做场景切分",
                "按镜头抽代表帧",
                "帧级/窗口级统计转场、运镜、色彩连续性",
            ],
        }

    def probe(self, source):
        raise NotImplementedError("ffmpeg adapter future work")

    def segment(self, source):
        raise NotImplementedError("ffmpeg adapter future work")

    def representative_frames(self, source, segments):
        raise NotImplementedError("ffmpeg adapter future work")


class MockAdapter(VideoAdapter):
    name = "mock"

    def plan(self, source):
        return {"adapter": self.name, "source": source, "steps": ["generate deterministic mock rhythm"]}

    def probe(self, source):
        seed = stable_seed(source)
        rng = random.Random(seed)
        duration_ms = rng.randint(12000, 98000)
        shot_count = rng.randint(6, 24)
        avg_shot_ms = max(250, int(duration_ms / shot_count))
        segments = []
        remaining = duration_ms
        for i in range(shot_count):
            if i == shot_count - 1:
                shot = remaining
            else:
                base = max(250, int(avg_shot_ms * rng.uniform(0.55, 1.45)))
                shot = min(base, remaining - (shot_count - i - 1) * 250)
            remaining -= shot
            segments.append({"index": i + 1, "start_ms": duration_ms - remaining - shot, "duration_ms": shot})
        return {
            "adapter": self.name,
            "duration_ms": duration_ms,
            "shot_count": shot_count,
            "segments": segments,
            "seed": seed,
        }

    def segment(self, source):
        return self.probe(source)["segments"]

    def representative_frames(self, source, segments):
        return [{"segment": s["index"], "frame": f"mock_frame_{s['index']:03d}.jpg"} for s in segments]


def build_rhythm_params(probe, adapter_name="mock"):
    segments = probe["segments"]
    durations = [s["duration_ms"] for s in segments]
    total = sum(durations) or 1
    avg = round(total / len(durations), 1)
    buckets = {"0-1s": 0, "1-2s": 0, "2-4s": 0, "4s+": 0}
    for d in durations:
        if d < 1000:
            buckets["0-1s"] += 1
        elif d < 2000:
            buckets["1-2s"] += 1
        elif d < 4000:
            buckets["2-4s"] += 1
        else:
            buckets["4s+"] += 1
    transition_types = [
        {"value": "hard_cut", "confidence": 0.82, "source": adapter_name, "detection_method": "cut-boundary-statistics"},
        {"value": "dissolve", "confidence": 0.41, "source": adapter_name, "detection_method": "frame-blend-estimate"},
    ]
    camera_moves = [
        {"value": "static", "confidence": 0.61, "source": adapter_name, "detection_method": "frame-drift-estimate"},
        {"value": "pan", "confidence": 0.34, "source": adapter_name, "detection_method": "optical-flow-placeholder"},
    ]
    return {
        "status": "mocked",
        "confidence": 0.5,
        "source": adapter_name,
        "detection_method": "mock-deterministic",
        "params": {
            "avg_shot_ms": avg,
            "shot_count": len(durations),
            "shot_length_distribution": {
                "buckets": buckets,
                "p10": sorted(durations)[max(0, int(len(durations) * 0.1) - 1)],
                "p50": sorted(durations)[len(durations) // 2],
                "p90": sorted(durations)[min(len(durations) - 1, int(len(durations) * 0.9))],
            },
            "transition_types": transition_types,
            "camera_moves": camera_moves,
            "pace_density": {
                "cuts_per_min": round(60000 / avg, 2),
                "segment_density": round(len(durations) / max(1, total / 60000), 3),
            },
            "color_continuity": {
                "mean_delta_e": round((probe["seed"] % 120) / 10.0, 2),
                "drift_rate": round((probe["seed"] % 100) / 1000.0, 3),
                "dominant_shift": "mock-shift",
            },
        },
        "summary": f"mock rhythm: {len(durations)} shots / avg {avg} ms",
    }


def merge_style_dna(visual, rhythm):
    payload = {"visual": visual, "rhythm": rhythm}
    signature = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {"visual": visual, "rhythm": rhythm, "signature": signature, "computed_at": now_iso()}


def cmd_mock(args):
    source = args.seed or args.source or "mock-video"
    adapter = MockAdapter()
    probe = adapter.probe(source)
    rhythm = build_rhythm_params(probe, adapter_name=adapter.name)
    out = {
        "version": "v0.1-draft",
        "source": {"origin": "mock", "id": source},
        "adapter": adapter.name,
        "probe": probe,
        "rhythm": rhythm,
        "style_dna": merge_style_dna(args.visual or {}, rhythm),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_merge_dna(args):
    visual = load_json(args.visual, {}) if args.visual else {}
    rhythm = load_json(args.rhythm, {}) if args.rhythm else {}
    print(json.dumps(merge_style_dna(visual, rhythm), ensure_ascii=False, indent=2))


def cmd_adapter_dry_run(args):
    adapter = FfmpegAdapter()
    print(json.dumps(adapter.plan(args.source), ensure_ascii=False, indent=2))


def cmd_validate(args):
    obj = load_json(args.rhythm, {})
    # 兼容 rhythm 直接输入，或完整 mock 结构里的 analysis.rhythm
    if isinstance(obj, dict) and "rhythm" in obj and "params" not in obj:
        obj = obj.get("rhythm", {})
    errors = []
    required = ["status", "params", "summary"]
    for k in required:
        if k not in obj:
            errors.append(f"missing {k}")
    params = obj.get("params", {})
    for k in ["avg_shot_ms", "shot_length_distribution", "transition_types", "camera_moves", "pace_density", "color_continuity"]:
        if k not in params:
            errors.append(f"missing params.{k}")
    for key in ["transition_types", "camera_moves"]:
        for i, item in enumerate(params.get(key, [])):
            if any(x not in item for x in ["confidence", "source", "detection_method"]):
                errors.append(f"{key}[{i}] missing confidence/source/detection_method")
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="StyleVault M3.0 analyze-video (architecture only)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mock", help="生成可复现 mock 视频分析")
    p.add_argument("seed", nargs="?", help="seed/source id")
    p.add_argument("--source", help="source name")
    p.add_argument("--visual", help="视觉层 JSON（可选）")
    p.set_defaults(func=cmd_mock)

    p = sub.add_parser("merge-dna", help="合并 visual + rhythm 生成 style_dna")
    p.add_argument("--visual", required=True, help="visual JSON 文件")
    p.add_argument("--rhythm", required=True, help="rhythm JSON 文件")
    p.set_defaults(func=cmd_merge_dna)

    p = sub.add_parser("adapter-dry-run", help="查看 ffmpeg adapter 计划，不依赖 ffmpeg")
    p.add_argument("source", help="视频源标识")
    p.set_defaults(func=cmd_adapter_dry_run)

    p = sub.add_parser("validate", help="校验 rhythm 结构")
    p.add_argument("rhythm", help="rhythm JSON 文件")
    p.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
