---
name: stylevault-analyze-video
version: 0.1.0
description: >-
  StyleVault 视频分析 (M3.0, architecture only)。通过统一 adapter 接口抽象视频处理，
  先用 mock 分析器验证 rhythm.params 与 style_dna 合并逻辑；不直接依赖 ffmpeg。
  Trigger: 用户说“视频分析 / M3.0 / 建视频风格模型”或需要校验 rhythm/style_dna。
---

# StyleVault Analyze-Video

## 目标
- 视频风格建模，不是抽帧工程。
- 优先保证可测量、可复现的 rhythm.params。
- Style DNA = visual(M2.5 editing_rules) ⊕ rhythm(M3)。

## 工作流
1. `mock`：基于 seed/source 生成可复现的节奏参数。
2. `adapter-dry-run`：只输出 adapter 计划，不调用 ffmpeg。
3. `merge-dna`：合并 visual 与 rhythm，生成 `style_dna.signature`。
4. `validate`：校验 rhythm.params 与 style_dna 结构。

## 约束
- 不直接依赖 ffmpeg；真实实现只需替换 `FfmpegAdapter`。
- 视频处理顺序：场景切分 → 镜头级采样 → 代表帧分析 → 时间窗口统计。
- `transition_types` / `camera_moves` 必须带 `confidence`、`source`、`detection_method`。
- 低置信度算法结果只作为候选，不当作确定事实。
- 冻结版 `schemas/item.schema.json` 不修改；新增字段仅进入 `schemas/drafts/`。

## 使用
```bash
python3 scripts/analyze_video.py mock demo-seed
python3 scripts/analyze_video.py adapter-dry-run sample.mp4
python3 scripts/analyze_video.py merge-dna --visual visual.json --rhythm rhythm.json
python3 scripts/analyze_video.py validate rhythm.json
```