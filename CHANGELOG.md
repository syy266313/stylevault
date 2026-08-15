# Changelog

StyleVault 变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 简化版，版本号语义化。

## [Unreleased]

## [0.4.3] - 2026-08-15

### Added
- **M3.0 Architecture Only**：
  - `stylevault-analyze-video` skill 骨架（统一 adapter 接口、mock 分析器、Style DNA 合并逻辑）；
  - `schemas/drafts/video.schema.json` 草案（rhythm.params + style_dna + transition_types/camera_moves 结构）；
  - `scripts/analyze_video.py` 支持 `mock` / `adapter-dry-run` / `merge-dna` / `validate`，不依赖 ffmpeg。

### Changed
- M3 定位明确为“视频风格建模”而非抽帧工程；上层流程不直接依赖 ffmpeg，未来只需实现 adapter。

## [0.4.2] - 2026-08-15

### Added
- **v0.4 冻结**：tag `v0.4.1` + 分支 `release/v0.4`；item.schema.json 标记 `x-status: frozen`。
- **开发文档**：docs/DEVELOPMENT.md（环境/工作流/提交规范/测试/同步）。
- **设计文档**（M3 前置评审）：
  - docs/DESIGN-style-embedding.md — 语义向量嵌入字段设计（analysis 嵌入为主路径）；
  - docs/DESIGN-rhythm-v2.md — rhythm 从标签升级为参数结构（六项视频指标）；
  - docs/DESIGN-M3-video-language-engine.md — 视频风格建模技术设计（切分/转场/运镜/节奏/色彩连续性 + Style DNA 合并）；
  - schemas/drafts/item.schema.v2.draft.json — v2 草案（rhythm 参数化 + embedding 细化 + style_dna 预留）。
- **Style DNA 概念**：visual（静态 editing_rules）⊕ rhythm（时间参数）→ 统一风格指纹，为 M6 剪辑引擎与 M4 语义检索奠基。

## [0.4.1] - 2026-08-15

### Added
- **Golden Dataset 20/20 全量分析完成**（gpt-5.6-terra Vision）：
  - 20 张图片全部 `done`，editing_rules 覆盖 100%；
  - 25 次调用 / 平均延迟 24.4s / 总 token ≈29.5 万（in 27.4万 + out 2.1万）；
  - 抽查质量：editing_rules 含具体色值/EV/百分比/焦段/色温（如 4300K、+0.6EV、4:5 裁切、旋转修正）。

### Fixed
- 标签正则允许下划线（`subject:printed_page` 不再误拒）。
- **HEIC 预处理**：HEIC 图片经 `heif-convert`（libheif-tools）转 JPEG 后再调 API，解决上游 502。
- `phase-b` 跳过视频条目（M3 处理），不再浪费调用。
- 依赖新增：`apk add libheif-tools`（HEIC 转码，ffmpeg 替代方案，体积小）。

## [0.4.0] - 2026-08-15

### Added
- **Phase B 视觉模型自动分析管线**（gpt-5.6-terra Vision）：
  - `analyze.py phase-b` 子命令：自动调用 OpenAI 兼容视觉 API（图片 base64 + 视觉提示词）→ JSON 解析 → 结构校验 → 写回 `analysis`（八维 + preference + summary + editing_rules）→ 队列移除；
  - API 配置可切换，模型名不写死：`STYLEVAULT_MODEL`（默认 gpt-5.6-terra）/ `OPENAI_BASE_URL` / `OPENAI_API_KEY` 环境变量 + `--model/--base-url/--api-key` CLI 覆盖；base URL 自动兼容 `/v1` 后缀；
  - 失败处理：API 错误/JSON 校验失败 → `status=error` + pipeline_log 审计，不写坏数据；
  - 降级路径保留（prompt/apply 手工模式）。
- 记录每次分析的 `latency_ms` 与 token `usage`（供 M2.5 校准统计）。

## [0.3.0] - 2026-08-15

### Added
- **M2.5 视觉分析质量校准**：
  - `editing_rules` 分析维度（schema + 校验 + 提示词模板）：可直接用于 AI 调色/剪辑/出图的可执行规则（aspect 作用域 + 含具体参数的指令）。
  - **Golden Dataset**（configs/golden-dataset.json）：20 张精选图片（6 生成风格图 + 2 网页截图 + 12 相册真实照片），带 ground truth 标注（内容确定的条目全维度标注，相册照片按 vision/OCR 线索标注、无把握维度 null 不计分）；全部已入库并打 `golden-dataset` collection。
  - **A/B 评测框架**（scripts/ab_test.py）：对 Golden Dataset 用两个多模态模型对比评测——准确率（vs golden，按维度）、标签稳定性（跨模型 Jaccard）、JSON 一致性（解析+结构校验）、平均延迟、token 成本；结果存 configs/ab_results/。

### Blocked
- **A/B 实测待模型接入**：当前环境 gpt-5.6-luna-high / gpt-5.6-luna-xhigh 模型条目未配置，且 minis-model-use 无可用模型（agent loop 组仅 deepseek 且不可调）。需在 Settings → Model Groups 添加模型后运行 `python3 scripts/ab_test.py`。

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
