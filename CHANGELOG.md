# Changelog

StyleVault 变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 简化版，版本号语义化。

## [Unreleased]

### Added (M4.0 deterministic local search)
- 新增 `stylevault-search` skill，基于 `item.json` 的标签、summary、editing_rules、type、collection 和 preference 提供本地 JSON 检索。
- 支持标签 AND/OR、元数据过滤、文本匹配、可解释评分、稳定排序和索引缺失/过期时从 item.json 降级扫描。
- 不使用 embedding、向量数据库、云端服务或 Style DNA；检索只读原始条目。

### Added (M3.3.1 generalization benchmark contract)
- 新增真实用户视频 benchmark 契约文档和空配置 manifest。
- benchmark 与 synthetic acceptance 隔离，仅生成泛化报告；holdout 不得用于调参，真实素材/帧/日志不入 Git。

### Added (M3.3 color continuity detection)
- 新增统一 `m3.3.v1` color metrics contract：exact-duration sampling axis、相邻 interval `mean_delta_e`、实际首尾时间跨度 `drift_rate`、interval `stable_ratio`。
- 在 `FfmpegAdapter` 内新增 color continuity detector，输出 `mean_delta_e`、`drift_rate`、`stable_ratio`、`dominant_shift`、confidence/provenance、采样和诊断信息。
- `dominant_shift` 由独立 detector 分类：`none`、`cool_to_warm`、`cool_to_warm_abrupt`、`alternating`、`cool_to_warm_via_neutral`、`unknown`。
- alternating/fade 增加周期、方向变化、transition window、neutral valley 等派生诊断，不替换统一核心指标。
- 5 个独立 synthetic color fixture 的 detector acceptance 达到 `5/5`；真实用户视频泛化仍未验证。

### Added (M3.2 frame detection)
- 在 `FfmpegAdapter` 内新增 ffmpeg 帧采样和 Pillow 帧级分析路径，所有 ffmpeg/ffprobe 调用仍封装在 adapter 内。
- 转场检测使用相对局部帧差、持续窗口、RGB 变化和全局亮度谷值，区分 `hard_cut`、`dissolve` 和 `fade_out_in`。
- 运镜检测使用镜头内部跨窗口块平移、尺度匹配和显著区域趋势，区分 `static`、`pan`、`zoom`，证据不足时输出 `unknown` candidate。
- 每个观测包含 `value`、`confidence`、`source`、`detection_method`、`candidate`、`status` 和采样窗口/诊断信息。
- 独立 M3.2 fixture acceptance 对 6 个 synthetic fixture 达到 `6/6`。
- 新增检测专项测试，覆盖阈值、采样参数、转场区分、误报约束、非法 confidence、文件不存在和超时错误。

### Fixed (M3.2.1 integration hardening)
- 新增 `analyze-m32` 正式 CLI，输出统一进入 `rhythm.params.transition_types` 与 `rhythm.params.camera_moves`。
- `analyze_m32()` 先消费 `segment()` 结果：相邻 segment 边界用于转场窗口，单个 segment 内用于运镜分析；事件携带 `segment_index`、`time_s` 或 `window_ms`。
- fixture evaluator 增加 transition 事件位置误差检查和严格 observation provenance 校验。
- 修正 handoff 中 detector commit 为 `19c6f53`；明确真实用户视频泛化尚未验证。

## [0.4.7] - 2026-08-15

### Fixed (M3.1.1 加固)
- **验收器缺失字段即失败**：`shot_count` / `avg_shot_ms` 缺失时不再"缺字段也通过"，`evaluate_video.py` 的 checks 改为 `is not None and <= 阈值`，summary 新增 `missing_fields` 统计。
- **M3.1 强制 segments**：`check_segment_integrity` 改为 prediction 无 segments 即失败（M3.1 验收必须携带根级或 `probe.segments`），不再跳过。
- **NaN/Infinity 拒绝**：`validate_segments` 与 `validate` 对所有数值字段（start/dur/duration/avg_shot_ms/分位数/confidence）增加 `math.isfinite` 校验。
- **ffprobe 健壮性**：malformed JSON、非对象结构、无法解析的时长、非法帧率字符串（如 `abc/def`、分母 0）、非有限 fps 均返回结构化 `RuntimeError`，不再 traceback。
- **scene_threshold 单位修正**：对外保留 normalized 0-1，`FfmpegAdapter` 内映射到 ffmpeg `scdet` 的原生 0-100 范围；构造时校验对外范围 [0,1]。
- **M3.3 门控**：独立 color-fixture acceptance route 就绪后允许执行 M3.3 proof；legacy M3.1 mock route 仍拒绝，避免用旧 ground truth 伪装 color acceptance。
- **新增测试**：`tests/test_m3_1_1_hardening.py`（19 用例）：缺失 shot_count/avg_shot_ms/segments 失败、NaN/Infinity 拒绝（segments 与 validate 两条路径）、malformed ffprobe JSON、非法帧率、阈值范围与单位常量。

## [0.4.6] - 2026-08-15

### Fixed (M3.1.1 契约修正)
- **overall_pace**：新增 `derive_overall_pace(avg_shot_ms)` 确定性规则（<1200ms=fast, <3000ms=medium, >=3000ms=slow），Mock 与 Ffmpeg 输出统一携带 `rhythm.overall_pace`。
- **验收按 milestone 拆分**：`evaluate_video.py` 新增 `--milestone M3.1|M3.2|M3.3`（默认 M3.1）；M3.1 只验收 probe/shot 统计/overall_pace/segment 完整性，不再因 M3.2 的 transition/camera 未实现而失败；`configs/video-test-suite.json` 改为 `acceptance_by_milestone` 结构。
- **cuts_per_min 统一定义**：`cuts_per_min = max(shot_count-1, 0) / duration_minutes`（切点数/分钟），Mock 与 Ffmpeg 一致；`segment_density = shot_count / duration_minutes` 保留区分。
- **confidence 误导修正**：Ffmpeg rhythm 顶层移除 `confidence=1.0`，改为分维度 `coverage`（probe/shot_statistics 各 1.0；transition/camera/color 为 0.0 + not-implemented-m3.x）。
- **scdet 解析可靠性**：抽出纯函数 `parse_scdet_output()`，支持 `=`/`:` 两种格式，过滤 0/越界/非有限/重复切点，无 scdet 输出时给出明确 warning，不把"解析失败"当"无切点"。
- **零时长 segment 防护**：`probe()` 拒绝无效时长；`validate_segments()` 校验正时长、首段从 0 开始、区间连续、总时长与 probe 一致；`segment()` 输出解析 warnings。
- **validate 增强**：校验 shot_count 正整数、avg_shot_ms>0、p10<=p50<=p90、confidence∈[0,1]、coverage 结构。
- **新增测试**：`tests/test_m3_1_1.py`（17 用例，unittest，不依赖真实 ffmpeg）：缺失 ffmpeg/ffprobe、ffprobe 失败、无视频流、零时长、scdet 解析（标准/冒号/空/重复/越界）、segment 完整性、cuts_per_min 一致性、overall_pace 派生、M3.1/M3.2 验收差异。

## [0.4.5] - 2026-08-15

### Added
- **M3.1 最小真实运行时**：
  - `FfmpegAdapter.probe()` 使用 ffprobe 读取时长、分辨率、帧率、编码器与格式；
  - `FfmpegAdapter.segment()` 使用 ffmpeg `scdet` 输出可复现镜头区间；
  - 输出 `shot_count`、`avg_shot_ms`、`shot_length_distribution` 与 `pace_density`；
  - `transition_types` / `camera_moves` 以 `unknown` 低置信度占位，明确记录 `confidence/source/detection_method`，等待 M3.2 实现。
- 无 ffmpeg/ffprobe 时返回结构化错误，不影响 MockAdapter。

### Changed
- 所有 ffmpeg/ffprobe 调用严格封装在 `FfmpegAdapter` 内，上层接口不变。

## [0.4.4] - 2026-08-15

### Added
- **M3.0.5 测试准备**：
  - 3 个视频分析测试样本 ground truth（快节奏剪辑 / 慢节奏长镜头 / 明显转场与运镜）；
  - 自动验收脚本 `scripts/evaluate_video.py`：比较 future FfmpegAdapter 输出与 ground truth 的 shot_count / avg_shot_ms / transition_types / camera_moves / overall_pace 误差；
  - `video-test-suite.json` 作为测试基准，不修改 v0.4.1 frozen schema。

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
