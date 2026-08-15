#!/usr/bin/env python3
"""StyleVault analyze-video (M3.0 architecture only)

- 不直接依赖 ffmpeg；通过统一 adapter 接口抽象。
- mock 模式可验证 rhythm.params 和 style_dna 合并逻辑。
- 未来只需实现 FfmpegAdapter 即可接入真实视频分析。
"""
import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
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


def derive_overall_pace(avg_shot_ms):
    """根据平均镜头时长派生整体节奏（M3.1 确定性规则，Mock/Ffmpeg 共用）。

    - avg_shot_ms < 1200  -> "fast"
    - 1200 <= avg < 3000  -> "medium"
    - avg_shot_ms >= 3000 -> "slow"
    """
    if avg_shot_ms < 1200:
        return "fast"
    if avg_shot_ms < 3000:
        return "medium"
    return "slow"


def parse_scdet_output(text, duration_s):
    """解析 ffmpeg scdet metadata 输出，返回 (cut_times, warnings)。

    支持 `lavfi.scd.time=1.250` 与 `lavfi.scd.time: 1.250` 两种格式。
    过滤：0、越界（>= duration_s）、非有限值。
    无任何 scdet 输出或无法解析时给出明确 warning，避免把"解析失败"
    与"视频确实没有切点"混为一谈。
    """
    warnings = []
    if not text or "lavfi.scd" not in text:
        return [], ["未找到任何 lavfi.scd metadata；请检查 ffmpeg 版本与 scdet 滤镜是否可用"]
    raw = []
    for match in re.finditer(r"lavfi\.scd\.time[=:]\s*([0-9.]+)", text):
        try:
            raw.append(float(match.group(1)))
        except ValueError:
            warnings.append(f"无法解析 scdet 时间值: {match.group(1)!r}")
    if not raw:
        return [], ["存在 lavfi.scd 输出但未解析到任何时间戳"]
    before = len(raw)
    cut_times = []
    for t in sorted(raw):
        if not math.isfinite(t) or t <= 0:
            warnings.append(f"忽略非有限/非正切点: {t}")
            continue
        if t >= duration_s:
            warnings.append(f"忽略越界切点 {t}s（duration={duration_s}s）")
            continue
        if not cut_times or abs(t - cut_times[-1]) > 1e-6:
            cut_times.append(t)
    if len(cut_times) < before:
        warnings.append(f"过滤了 {before - len(cut_times)} 个无效/重复切点")
    return cut_times, warnings


def validate_segments(segments, duration_ms, tolerance_ms=5.0):
    """校验镜头区间完整性：正时长、连续衔接、总时长与 probe 一致。返回 (ok, errors)。"""
    errors = []
    if not segments:
        return False, ["空 segments"]
    total = 0.0
    prev_end = 0.0
    for i, seg in enumerate(segments, 1):
        start = seg.get("start_ms")
        dur = seg.get("duration_ms")
        if not isinstance(start, (int, float)) or not isinstance(dur, (int, float)):
            errors.append(f"segments[{i}] 缺少数值字段")
            continue
        if not math.isfinite(start) or not math.isfinite(dur):
            errors.append(f"segments[{i}] 起点/时长非有限值: start={start}, dur={dur}")
            continue
        if dur <= 0:
            errors.append(f"segments[{i}] 零/负时长: {dur}ms")
        if i > 1 and abs(start - prev_end) > 1e-6:
            errors.append(f"segments[{i}] start 与前段 end 不连续: {start} != {prev_end}")
        if i == 1 and abs(start - 0.0) > 1e-6:
            errors.append(f"segments[1] 应从 0 开始: {start}")
        total += dur
        prev_end = start + dur
    if not math.isfinite(duration_ms) or duration_ms <= 0:
        errors.append(f"probe 时长无效（非有限/非正）: {duration_ms}")
    if abs(total - duration_ms) > tolerance_ms:
        errors.append(f"segments 总时长 {total}ms 与 probe 时长 {duration_ms}ms 偏差超过 {tolerance_ms}ms")
    return (len(errors) == 0), errors


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
    """真实运行时 adapter。所有 ffmpeg/ffprobe 调用必须封装在本类内。"""
    name = "ffmpeg"
    # scene_threshold 单位：归一化 0-1（与 ffmpeg scdet threshold 原生单位一致，直接透传）。
    # 若外部配置使用其他单位（如 0-100 百分比），必须在传入前转换，或在构造后显式归一化。
    SCENE_THRESHOLD_UNIT = "normalized-0-1"

    def __init__(self, scene_threshold=0.30, timeout=120):
        if not (0.0 <= scene_threshold <= 1.0):
            raise RuntimeError(
                f"scene_threshold={scene_threshold} 超出归一化范围 [0,1]"
                f"（单位: {self.SCENE_THRESHOLD_UNIT}，与 ffmpeg scdet threshold 一致）"
            )
        self.scene_threshold = scene_threshold
        self.timeout = timeout

    def _require_tools(self):
        missing = [name for name in ("ffprobe", "ffmpeg") if shutil.which(name) is None]
        if missing:
            raise RuntimeError(
                "缺少视频分析依赖: " + ", ".join(missing) +
                "。请安装 ffmpeg（包含 ffprobe），当前 M3.1 无法执行真实视频分析。"
            )

    def _run(self, command):
        try:
            return subprocess.run(command, capture_output=True, text=True,
                                  timeout=self.timeout, check=True)
        except FileNotFoundError as exc:
            raise RuntimeError(f"视频工具不可用: {exc.filename}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"视频分析命令超时（{self.timeout}s）: {' '.join(command)}") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()[-500:]
            raise RuntimeError(f"视频分析命令失败: {' '.join(command)}\n{detail}") from exc

    def plan(self, source):
        return {
            "adapter": self.name,
            "source": source,
            "scene_threshold": self.scene_threshold,
            "sampling_policy": "scene segmentation -> shot-level sampling -> representative frames -> window statistics",
            "steps": [
                "ffprobe 读取时长/帧率/分辨率",
                "ffmpeg scdet 做场景切分",
                "按镜头抽代表帧（后续阶段）",
                "帧级/窗口级统计转场、运镜、色彩连续性（后续阶段）",
            ],
        }

    def probe(self, source):
        self._require_tools()
        result = self._run([
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", source,
        ])
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"ffprobe 输出无法解析为 JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"ffprobe 输出结构异常: 期望对象，得到 {type(payload).__name__}")
        video_stream = next((s for s in payload.get("streams", []) if s.get("codec_type") == "video"), None)
        if not video_stream:
            raise RuntimeError(f"未找到视频流: {source}")
        try:
            duration = float(video_stream.get("duration") or payload.get("format", {}).get("duration") or 0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"无法解析视频时长 {video_stream.get('duration')!r}: {exc}") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise RuntimeError(f"无效的视频时长: {duration}s，无法进行场景切分: {source}")
        rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/1"
        try:
            num, den = rate.split("/", 1) if "/" in rate else (rate, "1")
            den_f = float(den)
            if den_f == 0:
                raise ValueError("分母为 0")
            fps = float(num) / den_f
        except ValueError as exc:
            raise RuntimeError(f"非法帧率值 {rate!r}: {exc}") from exc
        if not math.isfinite(fps):
            raise RuntimeError(f"帧率结果非有限值: {fps} ({rate!r})")
        return {
            "adapter": self.name,
            "source": source,
            "duration_ms": round(duration * 1000, 3),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": round(fps, 6),
            "codec": video_stream.get("codec_name"),
            "format": payload.get("format", {}).get("format_name"),
        }

    def segment(self, source):
        """使用 scdet 输出切点，并转换为可复现的镜头区间。"""
        self._require_tools()
        probe = self.probe(source)
        result = self._run([
            "ffmpeg", "-hide_banner", "-nostats", "-i", source,
            "-vf", f"scdet=threshold={self.scene_threshold},metadata=print",
            "-an", "-f", "null", "-",
        ])
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        duration_s = probe["duration_ms"] / 1000
        cut_times, warnings = parse_scdet_output(text, duration_s)
        boundaries = [0.0] + cut_times + [duration_s]
        segments = []
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
            if end <= start:
                continue  # 防御：拒绝零/负时长区间
            duration_ms = round((end - start) * 1000, 3)
            if duration_ms <= 0:
                continue
            segments.append({
                "index": index,
                "start_ms": round(start * 1000, 3),
                "duration_ms": duration_ms,
            })
        ok, errors = validate_segments(segments, probe["duration_ms"])
        if not ok:
            raise RuntimeError("镜头区间校验失败: " + "; ".join(errors))
        return {"probe": probe, "cut_times_s": cut_times, "segments": segments, "warnings": warnings}

    def representative_frames(self, source, segments):
        raise NotImplementedError("代表帧采样将在 M3.2/M3.3 实现；M3.1 只输出切分统计")


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
        "overall_pace": derive_overall_pace(avg),
        "coverage": {
            "probe": {"confidence": 1.0, "source": adapter_name, "detection_method": "mock-deterministic"},
            "shot_statistics": {"confidence": 1.0, "source": adapter_name, "detection_method": "mock-deterministic"},
            "transition_types": {"confidence": 0.5, "source": adapter_name, "detection_method": "mock-estimate"},
            "camera_moves": {"confidence": 0.5, "source": adapter_name, "detection_method": "mock-estimate"},
            "color_continuity": {"confidence": 0.5, "source": adapter_name, "detection_method": "mock-estimate"},
        },
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
                # 统一定义：cuts_per_min = 切点数/分钟 = max(shot_count-1, 0) / duration_minutes
                "cuts_per_min": round(max(0, len(durations) - 1) / max(total / 60000.0, 1e-9), 3),
                "segment_density": round(len(durations) / max(total / 60000.0, 1e-9), 3),
            },
            "color_continuity": {
                "mean_delta_e": round((probe["seed"] % 120) / 10.0, 2),
                "drift_rate": round((probe["seed"] % 100) / 1000.0, 3),
                "dominant_shift": "mock-shift",
            },
        },
        "summary": f"mock rhythm: {len(durations)} shots / avg {avg} ms",
    }


def build_segment_rhythm(segment_result):
    """把 adapter 的切分结果转换为 M3.1 可测量 rhythm.params。"""
    probe = segment_result["probe"]
    segments = segment_result["segments"]
    durations = [s["duration_ms"] for s in segments]
    total = sum(durations) or 1
    ordered = sorted(durations)
    avg = round(total / len(durations), 3) if durations else 0
    def percentile(index):
        return ordered[min(len(ordered) - 1, max(0, index))] if ordered else 0
    buckets = {"0-1s": 0, "1-2s": 0, "2-4s": 0, "4s+": 0}
    for duration in durations:
        if duration < 1000:
            buckets["0-1s"] += 1
        elif duration < 2000:
            buckets["1-2s"] += 1
        elif duration < 4000:
            buckets["2-4s"] += 1
        else:
            buckets["4s+"] += 1
    duration_minutes = max(total / 60000.0, 1e-9)
    return {
        "status": "partial",
        "source": "ffmpeg",
        "detection_method": "ffprobe + scdet",
        "overall_pace": derive_overall_pace(avg),
        "coverage": {
            "probe": {"confidence": 1.0, "source": "ffprobe", "detection_method": "ffprobe-metadata"},
            "shot_statistics": {"confidence": 1.0, "source": "ffmpeg", "detection_method": "scdet"},
            "transition_types": {"confidence": 0.0, "source": "ffmpeg", "detection_method": "not-implemented-m3.2"},
            "camera_moves": {"confidence": 0.0, "source": "ffmpeg", "detection_method": "not-implemented-m3.2"},
            "color_continuity": {"confidence": 0.0, "source": "future-m3.3", "detection_method": "not-implemented-m3.3"},
        },
        "params": {
            "avg_shot_ms": avg,
            "shot_count": len(durations),
            "shot_length_distribution": {
                "buckets": buckets,
                "p10": percentile(int(len(ordered) * 0.10)),
                "p50": percentile(int(len(ordered) * 0.50)),
                "p90": percentile(int(len(ordered) * 0.90)),
            },
            "transition_types": [{
                "value": "unknown",
                "confidence": 0.0,
                "source": "ffmpeg",
                "detection_method": "not-implemented-m3.2",
            }],
            "camera_moves": [{
                "value": "unknown",
                "confidence": 0.0,
                "source": "ffmpeg",
                "detection_method": "not-implemented-m3.2",
            }],
            "pace_density": {
                # 统一定义：cuts_per_min = 切点数/分钟 = max(shot_count-1, 0) / duration_minutes
                "cuts_per_min": round(max(0, len(durations) - 1) / duration_minutes, 3),
                "segment_density": round(len(durations) / duration_minutes, 3),
            },
            "color_continuity": {
                "status": "not_started",
                "source": "future-m3.3",
                "detection_method": "not-implemented-m3.3",
            },
        },
        "summary": f"ffmpeg scene segmentation: {len(durations)} shots / avg {avg} ms",
        "probe": probe,
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
    adapter = FfmpegAdapter(scene_threshold=args.scene_threshold)
    print(json.dumps(adapter.plan(args.source), ensure_ascii=False, indent=2))


def cmd_probe(args):
    try:
        print(json.dumps(FfmpegAdapter().probe(args.source), ensure_ascii=False, indent=2))
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "adapter": "ffmpeg"}, ensure_ascii=False, indent=2))
        return 2
    return 0


def cmd_segment(args):
    try:
        result = FfmpegAdapter(scene_threshold=args.scene_threshold).segment(args.source)
        output = build_segment_rhythm(result)
        output["segments"] = result["segments"]
        output["warnings"] = result["warnings"]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "adapter": "ffmpeg"}, ensure_ascii=False, indent=2))
        return 2
    return 0


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

    # M3.1.1：数值合理性校验
    shot_count = params.get("shot_count")
    if shot_count is None:
        errors.append("missing params.shot_count")
    elif not isinstance(shot_count, int) or shot_count < 1:
        errors.append(f"params.shot_count 应为正整数: {shot_count!r}")
    avg = params.get("avg_shot_ms")
    if avg is not None and (not isinstance(avg, (int, float)) or not math.isfinite(avg) or avg <= 0):
        errors.append(f"params.avg_shot_ms 应为正有限数: {avg!r}")
    dist = params.get("shot_length_distribution") or {}
    p10, p50, p90 = dist.get("p10"), dist.get("p50"), dist.get("p90")
    if None not in (p10, p50, p90):
        vals_ok = all(isinstance(v, (int, float)) and math.isfinite(v) for v in (p10, p50, p90))
        if not vals_ok or not (p10 <= p50 <= p90):
            errors.append(f"shot_length_distribution 应为有限值且满足 p10<=p50<=p90: {p10}/{p50}/{p90}")
    for key in ["transition_types", "camera_moves"]:
        for i, item in enumerate(params.get(key, [])):
            if any(x not in item for x in ["confidence", "source", "detection_method"]):
                errors.append(f"{key}[{i}] missing confidence/source/detection_method")
            conf = item.get("confidence") if isinstance(item, dict) else None
            if conf is not None and (not isinstance(conf, (int, float)) or not math.isfinite(conf) or not 0 <= conf <= 1):
                errors.append(f"{key}[{i}] confidence 应为有限值且在 [0,1]: {conf!r}")

    # M3.1.1：coverage 结构（存在时校验）
    coverage = obj.get("coverage")
    if coverage is not None:
        if not isinstance(coverage, dict) or not coverage:
            errors.append("coverage 应为非空 dict")
        else:
            for dim, entry in coverage.items():
                if not isinstance(entry, dict) or any(x not in entry for x in ["confidence", "source", "detection_method"]):
                    errors.append(f"coverage.{dim} missing confidence/source/detection_method")
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
    p.add_argument("--scene-threshold", type=float, default=0.30)
    p.set_defaults(func=cmd_adapter_dry_run)

    p = sub.add_parser("probe", help="使用 FfmpegAdapter 读取视频元数据")
    p.add_argument("source", help="视频文件路径")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("segment", help="使用 FfmpegAdapter 做最小场景切分")
    p.add_argument("source", help="视频文件路径")
    p.add_argument("--scene-threshold", type=float, default=0.30)
    p.set_defaults(func=cmd_segment)

    p = sub.add_parser("validate", help="校验 rhythm 结构")
    p.add_argument("rhythm", help="rhythm JSON 文件")
    p.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    result = args.func(args)
    if isinstance(result, int):
        sys.exit(result)


if __name__ == "__main__":
    main()
