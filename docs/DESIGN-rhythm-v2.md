# rhythm 参数化设计（v2 草案）

> 目标：将 rhythm 从"标签"升级为"参数结构"——为 M3 视频风格建模（Video Language Engine）定义输出契约。
> 状态：设计文档（v1.0）。v1 冻结版 rhythm 保持 {tags, summary, confidence, avg_shot_ms, shot_count}；v2 完整参数化。

## 1. 动机

v1 的 rhythm 只是标签（`rhythm:fast-cut`）+ 两个数字，无法支撑：
- 剪辑引擎需要镜头长度的**分布**（而非均值）
- 转场/运镜是视频语言的核心，v1 完全缺失
- 节奏密度曲线、色彩连续性无法用标签表达

## 2. v2 rhythm 结构（item.json 顶层 analysis.rhythm）

```jsonc
{
  "rhythm": {
    "status": "done",                // pending | done | error
    "tags": ["rhythm:fast-cut"],     // 保留：一句话节奏定性（供标签检索）
    "summary": "平均镜头 1.25s，硬切主导，开篇密集后放缓",
    "confidence": 0.88,
    "params": {
      "avg_shot_ms": 1250,           // 平均镜头时长（用户要求 ①）
      "shot_count": 42,              // 镜头总数
      "shot_length_distribution": {  // 镜头长度分布（用户要求 ②）
        "p10": 420, "p50": 1100, "p90": 2600,
        "bins": {"0-1s": 12, "1-2s": 18, "2-4s": 8, "4s+": 4}
      },
      "transition_types": {          // 转场类型占比（用户要求 ③）
        "hard_cut": 0.80, "dissolve": 0.10, "fade_in_out": 0.05, "wipe": 0.05
      },
      "camera_moves": {              // 运镜类型占比（用户要求 ④）
        "static": 0.40, "pan": 0.20, "tracking": 0.15, "handheld": 0.15, "zoom": 0.10
      },
      "pace_density": {              // 节奏密度（用户要求 ⑤）
        "cuts_per_min": 48,          // 全局：每分钟切点数
        "peak_cuts_per_min": 90,     // 峰值（最密集 30s 窗口）
        "curve": [0.8, 1.2, 0.9, ...]// 时间曲线：按 10% 时段归一化密度
      },
      "color_continuity": {          // 色彩连续性（用户要求 ⑥）
        "mean_delta_e": 3.2,         // 相邻帧平均色差 ΔE
        "drift_rate": 0.05,          // 主色调漂移速率
        "dominant_shift": "teal-orange→cool",  // 色相漂移描述
        "stable_ratio": 0.82         // 连续帧色差 < 阈值 的比例
      }
    },
    "editing_notes": [               // 剪辑建议（可并入 editing_rules）
      "开篇 3s 硬切建立节奏", "长镜头段落用叠化衔接"
    ]
  }
}
```

图片条目 `rhythm: null` 不变。

## 3. 检测来源（M3 实现）

| 参数 | 来源 | 方法 |
|---|---|---|
| avg_shot_ms / distribution / pace | ffmpeg scdet 切点时间戳 | 切点差分 → 直方图/分位数；分段密度 |
| transition_types | 切点前后 N 帧差异曲线 | 突变=hard_cut；渐变多帧=dissolve/fade（过渡宽度判定） |
| camera_moves | 镜头内帧间位移（光流/块匹配） | static/pan/tilt/zoom 模式 + 抖动熵=handheld |
| color_continuity | 逐秒帧 HSV/平均色 | 相邻 ΔE、主色序列漂移 |

## 4. 与 editing_rules 的关系

- `rhythm.params` 是**测量值**（检测得到的事实）
- `editing_rules`（aspect=rhythm）是**建议值**（LLM 基于测量生成的执行规则，如"镜头 1.2s 硬切为主"）
- 两者合并 → Style DNA 的节奏层（见 M3 设计文档）

## 5. Schema 草案

见 `schemas/drafts/item.schema.v2.draft.json`。
