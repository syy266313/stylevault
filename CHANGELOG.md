# Changelog

StyleVault 变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 简化版，版本号语义化。

## [Unreleased]

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
