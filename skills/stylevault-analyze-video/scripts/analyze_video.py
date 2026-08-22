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
import tempfile
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
    # 对外保留归一化 0-1；ffmpeg scdet 原生 threshold 实际为 0-100。
    # 这里显式做尺度映射，避免把 scdet 版本差异误当作阈值单位差异。
    SCENE_THRESHOLD_UNIT = "normalized-0-1"
    FFMPEG_SCDET_THRESHOLD_UNIT = "0-100"

    def __init__(self, scene_threshold=0.30, timeout=120):
        if not (0.0 <= scene_threshold <= 1.0):
            raise RuntimeError(
                f"scene_threshold={scene_threshold} 超出归一化范围 [0,1]"
                f"（单位: {self.SCENE_THRESHOLD_UNIT}，映射到 ffmpeg {self.FFMPEG_SCDET_THRESHOLD_UNIT}）"
            )
        self.scene_threshold = scene_threshold
        self.ffmpeg_scene_threshold = scene_threshold * 100.0
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
            "-vf", f"scdet=threshold={self.ffmpeg_scene_threshold},metadata=print",
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

    def encode_frame_sequence(self, frame_dir, output_path, fps):
        """将 fixture 生成的 PNG 帧编码为视频；ffmpeg 调用仅在 adapter 内。"""
        self._require_tools()
        if not os.path.isdir(frame_dir):
            raise RuntimeError(f"fixture 帧目录不存在: {frame_dir}")
        if not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
            raise RuntimeError(f"fixture fps 必须为正有限数: {fps}")
        self._run([
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-framerate", str(fps),
            "-i", os.path.join(frame_dir, "frame_%06d.png"),
            "-c:v", "mpeg4", "-q:v", "5", "-pix_fmt", "yuv420p",
            output_path,
        ])
        return output_path

    def sample_frames(self, source, output_dir, sampling_fps=12.0):
        """使用 ffmpeg 将视频采样为 PNG 帧；所有媒体调用仍在 adapter 内。"""
        self._require_tools()
        if not isinstance(sampling_fps, (int, float)) or not math.isfinite(sampling_fps) or sampling_fps <= 0:
            raise RuntimeError(f"sampling_fps 必须为正有限数: {sampling_fps}")
        os.makedirs(output_dir, exist_ok=True)
        self._run([
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-i", source,
            "-vf", f"fps={sampling_fps}",
            "-vsync", "0", "-q:v", "2",
            os.path.join(output_dir, "frame_%06d.png"),
        ])
        paths = sorted(
            os.path.join(output_dir, name)
            for name in os.listdir(output_dir)
            if name.endswith(".png")
        )
        if not paths:
            raise RuntimeError(f"ffmpeg 未生成采样帧: {source}")
        return [{"path": path, "time_s": index / float(sampling_fps)} for index, path in enumerate(paths)]

    @staticmethod
    def _load_frame(path, max_width=96):
        try:
            from PIL import Image
            image = Image.open(path).convert("RGB")
            if image.width > max_width:
                image = image.resize((max_width, max(1, round(image.height * max_width / image.width))))
            return {"rgb": image, "gray": image.convert("L")}
        except Exception as exc:
            raise RuntimeError(f"无法读取采样帧 {path}: {exc}") from exc

    @classmethod
    def _load_gray(cls, path, max_width=96):
        return cls._load_frame(path, max_width=max_width)["gray"]

    @staticmethod
    def _mean_abs(a, b):
        from PIL import ImageChops, ImageStat
        diff = ImageChops.difference(a, b)
        return float(sum(ImageStat.Stat(diff).mean) / len(ImageStat.Stat(diff).mean) / 255.0)

    @classmethod
    def _translation_score(cls, a, b, max_shift=8):
        """可解释的下采样整数块平移匹配，返回 dx/dy、改进度和残差。"""
        zero = cls._mean_abs(a, b)
        best = (0, 0, zero)
        width, height = a.size
        for dy in range(-max_shift, max_shift + 1):
            for dx in range(-max_shift, max_shift + 1):
                ax0, ax1 = max(0, dx), min(width, width + dx)
                ay0, ay1 = max(0, dy), min(height, height + dy)
                bx0, bx1 = max(0, -dx), min(width, width - dx)
                by0, by1 = max(0, -dy), min(height, height - dy)
                if ax1 <= ax0 or ay1 <= ay0:
                    continue
                acrop = a.crop((ax0, ay0, ax1, ay1))
                bcrop = b.crop((bx0, by0, bx1, by1))
                error = cls._mean_abs(acrop, bcrop)
                if error < best[2]:
                    best = (dx, dy, error)
        improvement = (zero - best[2]) / max(zero, 1e-6)
        return {"dx": best[0], "dy": best[1], "improvement": improvement, "residual": best[2], "raw_diff": zero}

    @staticmethod
    def _resize_center(image, scale):
        from PIL import Image
        width, height = image.size
        resized = image.resize((max(2, round(width * scale)), max(2, round(height * scale))))
        if resized.width >= width:
            left = (resized.width - width) // 2
            resized = resized.crop((left, 0, left + width, min(height, resized.height)))
        else:
            canvas = Image.new("L", (width, resized.height), 0)
            canvas.paste(resized, ((width - resized.width) // 2, 0))
            resized = canvas
        if resized.height >= height:
            top = (resized.height - height) // 2
            resized = resized.crop((0, top, width, top + height))
        else:
            canvas = Image.new("L", (width, height), 0)
            canvas.paste(resized, (0, (height - resized.height) // 2))
            resized = canvas
        return resized

    @classmethod
    def _scale_score(cls, a, b):
        candidates = (0.50, 0.60, 0.70, 0.80, 0.90, 0.94, 0.97, 1.0, 1.03, 1.06, 1.10, 1.20, 1.30, 1.50, 1.75, 2.0)
        errors = [(scale, cls._mean_abs(a, cls._resize_center(b, scale))) for scale in candidates]
        scale, error = min(errors, key=lambda item: item[1])
        baseline = dict(errors)[1.0]
        return {"scale": scale, "improvement": (baseline - error) / max(baseline, 1e-6), "residual": error, "candidates": errors}

    @staticmethod
    def _salient_extent(image):
        """Find a reproducible colored foreground extent for scale trend evidence."""
        pixels = image.convert("RGB").load()
        points = []
        for y in range(image.height):
            for x in range(image.width):
                r, g, b = pixels[x, y]
                if r > g * 1.25 and r > b * 1.25 and r > 80:
                    points.append((x, y))
        if not points:
            return None
        xs, ys = zip(*points)
        return {"left": min(xs), "right": max(xs), "top": min(ys), "bottom": max(ys), "area": len(points)}

    @staticmethod
    def _observation(value, confidence, source, method, threshold):
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise RuntimeError(f"检测 confidence 非法: {confidence}")
        confirmed = confidence >= threshold and value != "unknown"
        return {
            "value": value,
            "confidence": round(confidence, 3),
            "source": source,
            "detection_method": method,
            "candidate": not confirmed,
            "status": "confirmed" if confirmed else "candidate",
        }

    def _detect_transitions(self, frames, sampling_fps, confidence_threshold=0.7, time_offset_s=0.0):
        """Detect cut-adjacent events using relative temporal windows."""
        import statistics
        loaded = [self._load_frame(item["path"]) for item in frames]
        arrays = [item["gray"] for item in loaded]
        rgbs = [item["rgb"] for item in loaded]
        if len(arrays) < 3:
            return [self._observation("unknown", 0.0, "ffmpeg+Pillow", "frame-window-diff", confidence_threshold)]
        brightness = [sum(pixel for pixel in frame.getdata()) / (255.0 * frame.width * frame.height) for frame in arrays]
        diffs = [self._mean_abs(rgbs[i - 1], rgbs[i]) for i in range(1, len(rgbs))]
        local = max(statistics.median(diffs) * 4.0, 1e-4)
        hard_cut_threshold = max(local * 8.0, 0.12)
        candidates = []
        # A fade-out-in is a global brightness valley, not a local RGB spike.
        trough_index = min(range(len(brightness)), key=lambda i: brightness[i])
        if 0 < trough_index < len(brightness) - 1:
            edge_count = max(3, round(len(brightness) * 0.15))
            left_level = statistics.median(brightness[:edge_count])
            right_level = statistics.median(brightness[-edge_count:])
            valley = min(left_level, right_level) - brightness[trough_index]
            left_mono = sum(brightness[i] <= brightness[i - 1] + 0.012 for i in range(1, trough_index + 1)) / max(1, trough_index)
            right_mono = sum(brightness[i] >= brightness[i - 1] - 0.012 for i in range(trough_index + 1, len(brightness))) / max(1, len(brightness) - trough_index - 1)
            if valley >= 0.12 and left_mono >= 0.65 and right_mono >= 0.65:
                fade_start = max(0, trough_index - round(sampling_fps * 0.55))
                fade_end = min(len(diffs) - 1, trough_index + round(sampling_fps * 0.55))
                fade = self._observation("fade", min(0.98, 0.72 + min(0.22, valley)), "ffmpeg+Pillow", "global-brightness-valley+fade-out-in", confidence_threshold)
                fade["time_s"] = round(trough_index / float(sampling_fps), 3)
                fade["window_frames"] = [fade_start, fade_end]
                fade["brightness_detail"] = {"left": round(left_level, 4), "trough": round(brightness[trough_index], 4), "right": round(right_level, 4), "valley": round(valley, 4), "left_monotonicity": round(left_mono, 3), "right_monotonicity": round(right_mono, 3)}
                return [fade]
        for index, diff in enumerate(diffs):
            if diff >= hard_cut_threshold:
                candidates.append((index, index, "hard_cut", min(0.99, 0.72 + min(0.27, diff)), "frame-window-diff+short-spike"))
        # Find sustained relative changes even when every frame is below a fixed absolute threshold.
        sustained = [diff > max(local * 1.5, 0.004) for diff in diffs]
        start = None
        for index, active in enumerate(sustained + [False]):
            if active and start is None:
                start = index
            if start is not None and not active:
                end = index - 1
                if end - start + 1 >= max(3, round(sampling_fps * 0.20)):
                    candidates.append((start, end, "window", 0.0, "frame-window-relative-diff"))
                start = None
        observations = []
        for start, end, kind, confidence, method in candidates:
            left = max(0, start - max(2, round(sampling_fps * 0.15)))
            right = min(len(brightness) - 1, end + max(2, round(sampling_fps * 0.15)))
            window = brightness[left:right + 1]
            span = end - start + 1
            left_values = brightness[left:max(left + 1, start)]
            right_values = brightness[min(right, end + 1):right + 1]
            left_level = sum(left_values) / max(1, len(left_values))
            right_level = sum(right_values) / max(1, len(right_values))
            trough_index = min(range(len(window)), key=lambda i: window[i])
            trough = window[trough_index]
            valley = min(left_level, right_level) - trough
            midpoint = (start + end) // 2
            if kind == "hard_cut":
                value, detail, final_confidence = "hard_cut", method, confidence
            elif valley >= 0.08 and trough_index > 0 and trough_index < len(window) - 1:
                value = "fade"
                detail = "frame-window-brightness-valley+fade-out-in"
                final_confidence = min(0.98, 0.72 + min(0.24, valley))
            else:
                value = "dissolve"
                detail = "frame-window-relative-diff+sustained-blend"
                end_gap = abs(left_level - right_level)
                final_confidence = min(0.96, 0.68 + min(0.20, span / max(1.0, sampling_fps * 2.0)) + min(0.08, end_gap))
            observation = self._observation(value, final_confidence, "ffmpeg+Pillow", detail, confidence_threshold)
            observation["time_s"] = round(time_offset_s + midpoint / float(sampling_fps), 3)
            observation["window_frames"] = [start, end]
            observation["brightness_detail"] = {"left": round(left_level, 4), "trough": round(trough, 4), "right": round(right_level, 4), "valley": round(valley, 4)}
            observations.append(observation)
        # Deduplicate overlapping windows, keeping the strongest observation.
        result = {}
        for observation in observations:
            result[observation["value"]] = max(result.get(observation["value"], observation), observation, key=lambda item: item["confidence"])
        return list(result.values())

    def _detect_camera_moves(self, frames, sampling_fps, confidence_threshold=0.7):
        loaded = [self._load_frame(item["path"]) for item in frames]
        arrays = [item["gray"] for item in loaded]
        if len(arrays) < 3:
            return [self._observation("unknown", 0.0, "ffmpeg+Pillow", "intra-shot-motion", confidence_threshold)]
        extents = [self._salient_extent(item["rgb"]) for item in loaded]
        translations = []
        scales = []
        stride = max(1, len(arrays) // 8)
        for index in range(0, len(arrays) - stride, stride):
            first, second = arrays[index], arrays[index + stride]
            translation = self._translation_score(first, second)
            scale = self._scale_score(first, second)
            # Transition spikes are excluded from motion votes by raw-diff threshold.
            if translation["raw_diff"] <= 0.25:
                translations.append(translation)
                scales.append(scale)
        if not translations:
            return [self._observation("unknown", 0.0, "ffmpeg+Pillow", "intra-shot-motion", confidence_threshold)]
        dx = [item["dx"] for item in translations]
        dy = [item["dy"] for item in translations]
        shift_mag = [(x * x + y * y) ** 0.5 for x, y in zip(dx, dy)]
        scale_delta = [abs(item["scale"] - 1.0) for item in scales]
        extent_area = [item["area"] for item in extents if item]
        extent_growth = (extent_area[-1] - extent_area[0]) / max(1, extent_area[0]) if len(extent_area) >= 2 else 0.0
        extent_trend = sum(extent_area[i] >= extent_area[i - 1] for i in range(1, len(extent_area))) / max(1, len(extent_area) - 1) if len(extent_area) >= 2 else 0.0
        directional = max(sum(x > 0 for x in dx) / len(dx), sum(x < 0 for x in dx) / len(dx))
        pan_votes = [mag >= 0.8 and abs(x) >= abs(y) * 1.5 for x, y, mag in zip(dx, dy, shift_mag)]
        zoom_votes = [delta >= 0.03 for delta in scale_delta]
        pan_ratio = sum(pan_votes) / len(pan_votes)
        zoom_ratio = sum(zoom_votes) / len(zoom_votes)
        if pan_ratio >= 0.55 and directional >= 0.65:
            confidence = min(0.98, 0.65 + 0.30 * pan_ratio + 0.05 * directional)
            return [self._observation("pan", confidence, "ffmpeg+Pillow", "intra-shot-block-translation", confidence_threshold)]
        if zoom_ratio >= 0.55 or (extent_growth >= 0.35 and extent_trend >= 0.70):
            evidence = max(zoom_ratio, min(1.0, extent_growth))
            confidence = min(0.96, 0.62 + 0.32 * evidence)
            observation = self._observation("zoom", confidence, "ffmpeg+Pillow", "intra-shot-scale-matching+salient-extent-trend", confidence_threshold)
            observation["scale_detail"] = {"scale_delta_mean": round(sum(scale_delta) / len(scale_delta), 4), "scale_trend_ratio": round(zoom_ratio, 3), "extent_growth": round(extent_growth, 3), "extent_trend_ratio": round(extent_trend, 3)}
            return [observation]
        motion_ratio = sum(mag >= 0.8 for mag in shift_mag) / len(shift_mag)
        if motion_ratio <= 0.20 and sum(delta >= 0.03 for delta in scale_delta) / len(scale_delta) <= 0.20:
            confidence = min(0.98, 0.78 + 0.18 * (1.0 - motion_ratio))
            return [self._observation("static", confidence, "ffmpeg+Pillow", "intra-shot-motion", confidence_threshold)]
        return [self._observation("unknown", 0.35, "ffmpeg+Pillow", "intra-shot-motion", confidence_threshold)]

    @staticmethod
    def _with_segment_context(observations, segment_index, start_ms, end_ms):
        for item in observations:
            item["segment_index"] = segment_index
            item["window_ms"] = [round(start_ms, 3), round(end_ms, 3)]
        return observations

    def analyze_m32(self, source, sampling_fps=12.0, confidence_threshold=0.7):
        """对真实帧执行 M3.2 检测，按 segment 边界区分转场和镜头内运镜。"""
        if not isinstance(confidence_threshold, (int, float)) or not math.isfinite(confidence_threshold) or not 0 <= confidence_threshold <= 1:
            raise RuntimeError(f"confidence_threshold 必须在 [0,1]: {confidence_threshold}")
        if not isinstance(sampling_fps, (int, float)) or not math.isfinite(sampling_fps) or sampling_fps <= 0:
            raise RuntimeError(f"sampling_fps 必须为正有限数: {sampling_fps}")
        segment_result = self.segment(source)
        probe = segment_result.get("probe") or self.probe(source)
        segments = segment_result.get("segments") or [{"index": 1, "start_ms": 0.0, "duration_ms": probe["duration_ms"]}]
        actual_fps = min(float(sampling_fps), probe["fps"])
        with tempfile.TemporaryDirectory(prefix="stylevault_m32_frames_") as frame_dir:
            frames = self.sample_frames(source, frame_dir, sampling_fps=actual_fps)
            grouped = []
            for segment in segments:
                start_ms = float(segment["start_ms"])
                end_ms = start_ms + float(segment["duration_ms"])
                selected = [frame for frame in frames if start_ms / 1000.0 <= frame["time_s"] <= end_ms / 1000.0]
                grouped.append((segment, selected))
            camera_moves = []
            for segment, selected in grouped:
                if len(selected) < 3:
                    continue
                detected = self._detect_camera_moves(selected, actual_fps, confidence_threshold)
                camera_moves.extend(self._with_segment_context(detected, segment["index"], segment["start_ms"], segment["start_ms"] + segment["duration_ms"]))
            transitions = []
            for left, right in zip(grouped, grouped[1:]):
                left_segment, left_frames = left
                right_segment, right_frames = right
                boundary_frames = left_frames[-3:] + right_frames[:3]
                if len(boundary_frames) >= 3:
                    boundary_start_s = max(0.0, float(left_segment["start_ms"]) / 1000.0 + float(left_segment["duration_ms"]) / 1000.0 - 3.0 / actual_fps)
                    detected = self._detect_transitions(boundary_frames, actual_fps, confidence_threshold, time_offset_s=boundary_start_s)
                    transitions.extend(self._with_segment_context(detected, right_segment["index"], right_segment["start_ms"], right_segment["start_ms"] + right_segment["duration_ms"]))
            # If scdet exposes no boundary, retain a whole-video window so synthetic
            # fixtures remain observable while still recording the segment result.
            if not transitions and len(segments) == 1:
                detected = self._detect_transitions(frames, actual_fps, confidence_threshold)
                transitions.extend(self._with_segment_context(detected, segments[0]["index"], segments[0]["start_ms"], segments[0]["start_ms"] + segments[0]["duration_ms"]))
            if not camera_moves and len(segments) == 1:
                detected = self._detect_camera_moves(frames, actual_fps, confidence_threshold)
                camera_moves.extend(self._with_segment_context(detected, segments[0]["index"], segments[0]["start_ms"], segments[0]["start_ms"] + segments[0]["duration_ms"]))
        return {
            "source": source,
            "probe": probe,
            "segments": segments,
            "segment_result": {"cut_times_s": segment_result.get("cut_times_s", []), "warnings": segment_result.get("warnings", [])},
            "sampling": {"sampling_fps": actual_fps, "frame_count": len(frames)},
            "thresholds": {"confidence": confidence_threshold, "transition_active_diff": 0.08, "motion_shift_px": 0.8, "motion_scale_delta": 0.03},
            "transition_types": transitions,
            "camera_moves": camera_moves,
        }


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


def cmd_analyze_m32(args):
    try:
        adapter = FfmpegAdapter(scene_threshold=args.scene_threshold)
        result = adapter.analyze_m32(args.source, sampling_fps=args.sampling_fps, confidence_threshold=args.confidence_threshold)
        segment_result = {"probe": result["probe"], "segments": result["segments"]}
        rhythm = build_segment_rhythm(segment_result)
        rhythm["status"] = "partial"
        rhythm["source"] = "ffmpeg+Pillow"
        rhythm["detection_method"] = "ffprobe+scdet+frame-windows"
        rhythm["params"]["transition_types"] = result["transition_types"]
        rhythm["params"]["camera_moves"] = result["camera_moves"]
        rhythm["coverage"]["transition_types"] = {"confidence": max((x["confidence"] for x in result["transition_types"]), default=0.0), "source": "ffmpeg+Pillow", "detection_method": "frame-window-analysis"}
        rhythm["coverage"]["camera_moves"] = {"confidence": max((x["confidence"] for x in result["camera_moves"]), default=0.0), "source": "ffmpeg+Pillow", "detection_method": "intra-segment-analysis"}
        rhythm["segments"] = result["segments"]
        output = {"version": "v0.1-draft", "source": {"origin": "file", "path": args.source}, "adapter": "ffmpeg", "probe": result["probe"], "segments": result["segments"], "sampling": result["sampling"], "thresholds": result["thresholds"], "rhythm": rhythm}
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

    p = sub.add_parser("analyze-m32", help="使用 FfmpegAdapter 执行 M3.2 帧级分析")
    p.add_argument("source", help="视频文件路径")
    p.add_argument("--sampling-fps", type=float, default=12.0)
    p.add_argument("--confidence-threshold", type=float, default=0.70)
    p.add_argument("--scene-threshold", type=float, default=0.30)
    p.set_defaults(func=cmd_analyze_m32)

    p = sub.add_parser("validate", help="校验 rhythm 结构")
    p.add_argument("rhythm", help="rhythm JSON 文件")
    p.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    result = args.func(args)
    if isinstance(result, int):
        sys.exit(result)


if __name__ == "__main__":
    main()
