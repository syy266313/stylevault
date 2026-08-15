# Changelog

StyleVault 变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 简化版，版本号语义化。

## [Unreleased]

## [0.2.0] - 2026-08-15

### Added
- **M2 图片分析**：`stylevault-analyze-image` skill（v1.0.0）——两级分析管线：
  - Phase A 本地特征：apple-vision analyze（classify/faces/ocr）+ pillow（主色调 Top5/亮度/饱和度）→ `vision` 字段，幂等可重跑；
  - Phase B 语义分析：提示词生成（`prompt_b.md`，含特征快照+标签本体+输出要求）→ agent 执行 → 严格 JSON 校验写回（八维 + preference + summary）；
  - 低置信度维度（<0.6）自动标记 `needs_review`；校验失败留 `status=error` 不写坏数据；
  - 队列消费（`apply` 后自动移除）+ `rebuild-index` 聚合索引（24 个标签）。
- 持续集成工作流：PROJECT.md + CHANGELOG.md 提交前自动更新，规范提交信息（feat/fix/docs/…）。
- 远程仓库接入：github.com/syy266313/stylevault，素材文件不入库（.gitignore）。

### Changed
- **降级模式约束**（重要）：当前环境无多模态视觉模型（minis-model-use 无模型、无 API key、read_image 不注入像素）→ Phase B 由 agent 基于来源上下文+特征快照保守推理，信息不足的维度低置信度 → `needs_review`。接入多模态模型后 prompt_b.md 直接复用，无需改管线。

### Fixed
- `apply` 默认分析文件路径（回退 `<item_dir>/analysis.json`）。
- `phase-a` 自动清理队列中的失效条目。
- `pillow_features` 异常降级（坏图不阻塞 Phase A）。

## [0.1.0] - 2026-08-15

### Added
- **M0 基建**：项目目录骨架（items/indexes/skills/schemas/configs）、item.json JSON Schema v1（八维分析 + preference + analyze_version + embedding 预留）、八维标签本体（subject/style/mood/color/composition/lighting/camera/rhythm）、分析管线版本配置、标签聚合索引初始化。
- **M1 采集存储**：`stylevault-ingest` skill（v1.0.0）——三通道采集（附件 / apple-photos / URL 网页）、SHA-1 内容去重（重复素材追加 `source.refs` 不建新条目）、采集与分析解耦（骨架 `status=pending` 入 `indexes/queue.json`）、网页标题/URL 记录、MIME 标准化。
- 架构文档 v0.2 定稿（ARCHITECTURE.md）。

### Fixed
- `apple-photos list -q` 裸数据输出兼容（无 `ok` 包装键误判失败）。
- `get_page_info` 的 title 从 `data.text` 解析（非独立字段）。
- MIME 标准映射（`image/jpg` → `image/jpeg`）。

### Technical Notes
- 仓库：github.com/syy266313/stylevault（公开）。
- 素材原文件不入 git（.gitignore），仅版本化元数据。
