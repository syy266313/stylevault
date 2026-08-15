---
name: stylevault-analyze-image
version: 1.0.0
description: >-
  StyleVault 图片分析 (M2)。消费 stylevault-ingest 产出的分析队列，对图片条目执行
  两级分析：Phase A 本地确定性特征（apple-vision classify/faces/ocr + pillow
  主色调/亮度/饱和度 → 写 vision 字段）；Phase B 语义分析（构图/风格/情绪/色彩/
  光线/摄影语言/偏好评分，agent 看图输出严格 JSON → 校验写回 analysis 字段）。
  幂等可重放；低置信度标记 needs_review；完成后重建 tags.json 索引。
  Trigger: 用户说"分析新入库的/跑分析/分析图片"或队列有 pending 条目时。
---

# StyleVault Analyze-Image (图片两级分析)

## 工作流

1. **确认待分析条目**：
   ```
   python3 scripts/analyze.py queue        # 待分析队列
   python3 scripts/analyze.py status       # 全库状态总览
   ```
2. **Phase A 本地特征**（快，脚本化）：
   ```
   python3 scripts/analyze.py phase-a queue    # 队列全部；也可 item_id | all
   python3 scripts/analyze.py phase-a <id> --force   # 重跑
   ```
   产出：`vision` 字段（classifications/faces/ocr/palette/brightness/saturation/尺寸）。
3. **Phase B 语义分析**（自动模式，M2.5 默认）：
   ```
   python3 scripts/analyze.py phase-b queue      # 队列全部；也可 item_id | all
   python3 scripts/analyze.py phase-b <id> --force   # 重跑覆盖
   ```
   自动调用视觉模型 API（OpenAI 兼容，支持图片输入）→ 解析 JSON → 校验 → 写回
   `analysis`（八维 + preference + summary + **editing_rules**）→ 队列移除。
   API 配置通过环境变量（模型名不写死，可切换）：
   ```
   STYLEVAULT_MODEL=gpt-5.6-terra    # 默认值即 gpt-5.6-terra
   OPENAI_BASE_URL=<中转站 API 地址>   # 自动兼容 /v1 后缀
   OPENAI_API_KEY=<API Key>
   ```
   也支持 CLI 覆盖：`--model X --base-url Y --api-key Z`（优先级高于环境变量）。
   失败处理：API 错误/JSON 校验失败 → `status=error` + pipeline_log 记录，不写坏数据。
   （降级路径保留：`prompt <id>` 生成提示词 + 人工/agent 输出 + `apply <id>` 写回。）

## 规则

- **幂等**：已有 vision/analysis 的条目跳过（`--force` 重跑）；重跑不重复消耗。
- **analyze_version**：从 configs/pipeline.json 读取；每次运行写 pipeline_log（可审计/重放）。
- **低置信度**：任一维度 confidence < 0.6 → 整条目 `needs_review`，不阻塞后续分析。
- **图片条目 rhythm 必须为 null**（视频节奏在 M3 处理）。
- **标签取值**：优先使用 configs/tag-ontology.json 本体中的值，可新增但须贴切。

## 降级模式（当前环境重要约束）

当前 Minis 环境**无多模态视觉模型**（minis-model-use 无模型、无外部 API key、
read_image 不注入像素内容）→ agent 无法真正"看图"。

降级策略（已内置在流程中）：
1. Phase A 的确定性特征（classify/faces/palette/亮度/饱和度）是当前唯一视觉依据；
2. Phase B 分析必须基于**来源上下文 + 特征快照**保守推理，禁止编造细节；
3. 信息不足的维度给低 confidence（<0.6）→ 条目自动 `needs_review`，等待人工复核；
4. summary 中注明"降级模式推断"。

升级路径：接入多模态模型（minis-model-use 配置模型或设置 API key）后，
agent 用 read_image 真正看图，prompt_b.md 已就绪可直接复用，无需改管线。

## 验收自测

```
python3 scripts/analyze.py queue
python3 scripts/analyze.py phase-a queue          # Phase A 本地特征
python3 scripts/analyze.py phase-b queue          # Phase B 视觉模型（需 API 配置）
python3 scripts/analyze.py status
python3 scripts/analyze.py rebuild-index
```

## 边界

- 视频条目本阶段只跑 Phase A 图片特征（抽帧/节奏在 M3 的 analyze-video）。
- 不做 OCR 语义提取、不做风格迁移/生成。
