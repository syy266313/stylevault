# M3 技术设计：Video Language Engine（视频风格建模）

> 状态：设计文档 v1.0（v0.4 冻结后评审）。M3 目标**不是视频抽帧，而是视频风格建模**——
> 把视频的时间维度语言（镜头/转场/运镜/节奏/色彩流）量化为结构化参数。
> 前置：v1 冻结（release/v0.4）；ffmpeg 安装（M3.0 完成）；rhythm v2 参数结构（本系列设计）。

## 1. 定位与目标

输入：视频条目（`items/<id>/source.mp4`，已在 vault）
输出：`item.json.analysis.rhythm`（v2 参数结构）+ 视频版 `editing_rules` + `style_dna`（合并层）

六大建模指标（用户验收口径）：
1. **平均镜头时长** avg_shot_ms
2. **镜头长度分布** shot_length_distribution（分位数 + 直方图）
3. **转场类型** transition_types（硬切/叠化/淡入淡出/划像 占比）
4. **运镜类型** camera_moves（固定/摇/移/推拉/手持 占比）
5. **节奏密度** pace_density（每分钟切点 + 峰值 + 时间曲线）
6. **色彩连续性** color_continuity（相邻帧 ΔE / 主色漂移 / 稳定比例）

## 2. 架构

```
L4 Agent 编排: stylevault-analyze-video skill（消费队列中的视频条目）
├── M3.1 时间轴分析（ffmpeg，确定性）
│   ├── scdet 场景切分 → 切点时间戳序列 → avg_shot_ms / 分布 / pace_density
│   ├── 切点前后帧过渡分析 → transition_types
│   ├── 镜头内帧对位移估计 → camera_moves
│   └── 逐秒帧采样 → HSV/平均色 → color_continuity
├── M3.2 代表帧提取（ffmpeg）
│   └── 每个镜头取 1 代表帧 → frames/ 目录
├── M3.3 复用 analyze-image Phase A + Phase B
│   ├── 代表帧跑 apple-vision + pillow（本地特征）
│   └── 视觉模型分析帧序列 + 时间轴参数 → 八维标签 + rhythm 语义 + editing_rules(视频)
└── M3.4 Style DNA 合并
    └── 视觉层（八维 + editing_rules） ⊕ 节奏层（rhythm.params） → style_dna
```

依赖：`apk add ffmpeg`（M3.0）；其余复用现有（pillow / libheif / apple-vision / gpt-5.6-terra 视觉 API）。

## 3. 检测方法详述

### 3.1 场景切分与镜头时长（① ② ⑤）
```
ffmpeg -i source.mp4 -vf "scdet=threshold=0.30,metadata=print:file=scenes.log" -an -f null -
```
- 解析 scdet 输出的 `lavfi.scd.time` → 切点序列 `[t1, t2, ...]`
- 镜头时长 = 切点差分（末镜头 = 总时长 - 最后切点）
- 统计：均值 / 分位数（p10/p50/p90）/ 直方图 bins
- 节奏密度：全局 cuts/min；滑动 30s 窗口找峰值；10% 时段归一化曲线

### 3.2 转场类型（③）
- 每个切点取前后各 4 帧，计算逐帧差异曲线
- 判定：单帧突变 → hard_cut；多帧线性渐变（过渡宽 0.3-1s）→ dissolve/fade（依据亮度整体变化）
- 输出各类型占比

### 3.3 运镜类型（④）
- 镜头内取 2-3 个时间点帧对，用块匹配/相位相关估计全局位移向量
- 模式分类：
  - |v|≈0 且低抖动 → static
  - 匀速单向 → pan/tilt（方向决定）
  - 位移随位置线性缩放 → zoom
  - 位移大且抖动熵高 → handheld
  - 规则平移跟随 → tracking（启发式，可与 handheld 合并上报）
- 输出占比；实现用 ffmpeg 抽帧 + numpy/pillow 块匹配（无 opencv，musl 约束）

### 3.4 色彩连续性（⑥）
- 逐秒帧 → 下采样 32x32 → HSV 均值/主色
- 相邻帧 ΔE（RGB 空间欧氏，标准化）→ mean_delta_e
- 主色调序列 → 漂移速率（相邻主色变化均值）、色相漂移描述（如 teal-orange→cool）
- stable_ratio = ΔE < 阈值帧占比

## 4. Style DNA：与 editing_rules 的合并

**Style DNA = 素材的完整风格指纹**（可读 JSON + 可算向量，见 style_embedding 设计）：

```jsonc
{
  "style_dna": {
    "visual": {                          // 静态层（M2.5 产物）
      "dimensions": { "style": ["style:cyberpunk"], "color": [...], ... },
      "editing_rules": [ {"aspect": "color", "rule": "..."}, ... ]   // 调色/构图静态规则
    },
    "rhythm": {                          // 时间层（M3 产物）
      "params": { "avg_shot_ms": 1250, "transition_types": {...}, "camera_moves": {...},
                  "pace_density": {...}, "color_continuity": {...} },
      "editing_rules": [ {"aspect": "rhythm", "rule": "镜头 1.2s 硬切为主，开篇 3s 加速"} ]
    },
    "signature": "cyberpunk|fast-cut|neon|low-key|tracking",  // 风格签名串（检索友好）
    "computed_at": "2026-08-15T17:00:00+08:00"
  }
}
```

合并机制：
1. **测量**（M3.1，确定性）：rhythm.params 是事实；
2. **语义**（M3.3，LLM）：基于帧序列 + params 生成 rhythm 标签/summary/editing_notes + 视频 editing_rules；
3. **合并**（M3.4，确定性）：visual.editing_rules（静态）+ rhythm.editing_rules（时间）→ style_dna；
4. **可算化**（M4）：style_dna 序列化 → embedding（style_embedding 设计）。

用途（M6 剪辑引擎输入）：镜头选择（按 avg_shot/运镜匹配）、节奏匹配（pace_density 曲线对齐）、
调色约束（visual.editing_rules）、跨素材风格比对（DNA 距离）。

## 5. 输出契约（item.json 变更，走 v2 草案）

- `analysis.rhythm` → v2 参数结构（DESIGN-rhythm-v2.md）
- `analysis.editing_rules` 追加 aspect=rhythm 的规则
- `style_dna` 顶层新增（v2）
- `vision.frames`：代表帧缩略图清单（frames/ 目录，不占大空间）
- `pipeline_log` 记录 video 分析事件（版本可重放）

## 6. 里程碑分解

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M3.0 | 安装 ffmpeg；video skill 骨架；队列中视频条目盘点 | ffmpeg 可用 |
| M3.1 | 时间轴分析：切分/分布/节奏密度（确定性） | 3 个视频产出 avg_shot/distribution/pace |
| M3.2 | 转场类型 + 运镜类型检测 | transition_types/camera_moves 占比 |
| M3.3 | 色彩连续性 + 代表帧复用 M2 分析 | color_continuity + 帧语义标签 |
| M3.4 | 语义合并 + style_dna | 视频条目完整 Style DNA，editing_rules 100% 覆盖 |
| M3.5 | Golden 视频校准（3+3 条目）+ 文档 | 验收通过 |

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 无 opencv（musl） | 运镜用 ffmpeg 抽帧 + numpy/pillow 块匹配，不用 cv2 |
| 长视频分析慢 | 采样策略：切分全量跑（快），帧分析每镜头 1 帧 |
| scdet 阈值不通用 | threshold 可配置（--scene-threshold），默认 0.30 |
| 视频大文件 | 只存 frames/ 代表帧 + 参数，原片可选外链 |
| 转场/运镜误判 | 输出占比 + confidence；语义层 LLM 复核 |
