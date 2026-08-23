---
name: stylevault-analyze-video
version: 0.2.1
description: >-
  StyleVault 视频分析 (M3.1.1+加固)。通过统一 adapter 接口抽象视频处理：
  MockAdapter 验证 rhythm.params 与 style_dna 合并逻辑；FfmpegAdapter 提供
  probe/segment 最小真实运行时（ffmpeg/ffprobe 调用仅限 adapter 内部）。
  Trigger: 用户说“视频分析 / M3 / 建视频风格模型”或需要校验 rhythm/style_dna。
---

# StyleVault Analyze-Video

## 目标
- 视频风格建模，不是抽帧工程。
- 优先保证可测量、可复现的 rhythm.params。
- Style DNA = visual(M2.5 editing_rules) ⊕ rhythm(M3)。

## 节奏参数契约（M3.1.1）
- `overall_pace`：由 `avg_shot_ms` 确定性派生：`<1200ms=fast`，`<3000ms=medium`，`>=3000ms=slow`。Mock 与 Ffmpeg 输出一致。
- `pace_density.cuts_per_min`：切点数/分钟 = `max(shot_count-1, 0) / duration_minutes`（Mock/Ffmpeg 同一公式）。
- `pace_density.segment_density`：镜头数/分钟 = `shot_count / duration_minutes`。
- 顶层不用整体 confidence 表示完整分析可信度；改用分维度 `coverage`（每维带 confidence/source/detection_method）。
- `transition_types` / `camera_moves` 必须带 `confidence`、`source`、`detection_method`；低置信度结果只作候选，不当作事实。M3.1 的基础 rhythm 输出仍保留 `unknown` 占位，M3.2 的 `analyze-m32` 输出真实帧级观测。
- `scene_threshold` 对外单位为 normalized 0-1；`FfmpegAdapter` 内部显式映射到 ffmpeg `scdet` 的 0-100 原生范围。
- 零时长、不连续、总时长与 probe 不符的 segments 视为无效（`validate_segments`）；NaN/Infinity 一律拒绝。

## M3.2 Fixture 基础
- `configs/video-m3.2-fixtures.json` 是独立于 M3.1 mock suite 的 synthetic fixture 规格。
- 当前包含 `static_hard_cut`、`static_dissolve`、`static_fade`、`pan_horizontal`、`zoom_in`、`no_motion` 六个 fixture。
- `scripts/m3_2_fixtures.py` 按规格在测试运行时生成帧并通过 `FfmpegAdapter` 编码；`scripts/evaluate_m32_fixtures.py` 运行真实帧级检测并与 synthetic ground truth 比对。
- M3.2 已实现：转场使用相对窗口 RGB diff、持续变化和亮度谷值；运镜使用跨窗口块平移、尺度匹配和显著区域趋势。
- 低置信度结果标记为 `candidate`，不能作为确认事实；`unknown` 不得通过 M3.2 acceptance。

## 工作流
1. `mock`：基于 seed/source 生成可复现的节奏参数（含 overall_pace/coverage）。
2. `adapter-dry-run`：只输出 adapter 计划，不调用 ffmpeg。
3. `probe`：通过 `FfmpegAdapter` 调用 ffprobe 读取媒体元数据（malformed JSON/非法帧率/无效时长均返回结构化错误）。
4. `segment`：通过 `FfmpegAdapter` 调用 ffmpeg scdet，输出镜头数量、平均镜头时长和长度分布；无 ffmpeg 时返回结构化错误。
5. `merge-dna`：合并 visual 与 rhythm，生成 `style_dna.signature`。
6. `validate`：校验 rhythm 结构、数值合理性（shot_count/avg_shot_ms/分位数/confidence/coverage），拒绝 NaN/Infinity。
7. `evaluate_video.py --milestone M3.1|M3.2|M3.3`：按里程碑验收：
   - M3.1：shot_count/avg_shot_ms/overall_pace **缺失即失败**；**必须携带 segments**（根级或 probe.segments），否则失败。
   - M3.2：必须使用 `configs/video-m3.2-fixtures.json`，6 个 fixture 全部通过；unknown 或低置信度 candidate 不能通过。
   - M3.3：仅允许通过独立 color-fixture acceptance route；legacy M3.1 mock route 继续拒绝。

## 约束
- ffmpeg/ffprobe 调用只能出现在 `FfmpegAdapter` 内部；上层流程不直接依赖 ffmpeg。
- `scene_threshold` 对外单位为归一化 0-1；`FfmpegAdapter` 内部映射到 ffmpeg `scdet` 原生 0-100 范围（0.30 -> 30.0）。
- 视频处理顺序：场景切分 → 镜头级采样 → 代表帧分析 → 时间窗口统计。
- 冻结版 `schemas/item.schema.json` 不修改；新增字段仅进入 `schemas/drafts/`。

## 使用
```bash
python3 scripts/analyze_video.py mock demo-seed
python3 scripts/analyze_video.py adapter-dry-run sample.mp4
python3 scripts/analyze_video.py probe sample.mp4
python3 scripts/analyze_video.py segment sample.mp4 --scene-threshold 0.30
python3 scripts/analyze_video.py analyze-m32 sample.mp4
python3 scripts/analyze_video.py merge-dna --visual visual.json --rhythm rhythm.json
python3 scripts/analyze_video.py validate rhythm.json
python3 scripts/evaluate_video.py --ground-truth configs/video-test-suite.json --prediction prediction.json --milestone M3.1
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## 验收状态
- M3.1.1 代码路径和真实 runtime 已验证；ffmpeg 1229403 的 probe/segment 与 M3.1 acceptance 已通过。
- M3.2 synthetic fixture 与帧级检测已验证；6/6 fixture acceptance 通过。
- M3.2.1 integration hardening adds the formal `analyze-m32` CLI, unified `rhythm.params` output, segment-aware event context, and event-position validation.
- Real user video generalization remains unverified.
- M3.3 color fixture 与 detector 已完成：`configs/video-m3.3-color-fixtures.json` 定义 5 个独立 synthetic color sequence，`scripts/evaluate_m33_color_fixtures.py` 执行 probe、reference 和 detector acceptance。
- metrics contract 固定为 `m3.3.v1`：exact-duration sampling、相邻 interval mean Delta E、实际首尾 drift rate、stable interval ratio。

- M3.3 acceptance：5/5 fixture 通过；legacy M3.1 mock route 不得用于 color acceptance。
- M3.3.1 `scripts/validate_m331_benchmark.py` 只做独立 manifest 校验和 report scaffold；不采集真实媒体、不连接 milestone acceptance、不写回 item/index。