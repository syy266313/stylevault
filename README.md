# StyleVault

个人视觉审美知识库：本地优先，文件即数据库。

远程仓库：<https://github.com/syy266313/stylevault>

## Agent 首次启动

任何新的架构师、编码 Agent、OpenMinis 会话或 TRAE 会话，都先按以下顺序阅读：

1. `README.md`（本文件，项目入口和当前操作规约）
2. `AGENTS.md`（编码 Agent 合同）
3. `docs/ARCHITECTURE_CONTEXT.md`（用户环境、分工和长期架构约束）
4. `docs/AGENT_HANDOFF_M3.md`（当前阶段、提交、测试和阻塞状态）
5. `docs/PROJECT_CONTEXT.md`（详细历史上下文）
6. 与当前任务相关的 `docs/DESIGN-*.md` 和 `skills/*/SKILL.md`

读取后先执行：

```sh
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

不要重新要求用户重复已经写入这些文件的信息。当前状态以 `docs/AGENT_HANDOFF_M3.md` 和远程 Git 状态为准；本 README 只保存稳定入口和重要基线。

## 项目目标

用户收藏图片、视频和网页案例，系统分析构图、色彩、光影、镜头语言、剪辑节奏和风格标签，形成可检索的审美知识资产，未来辅助 AI 自动剪辑。

## 当前基线

- M3.3 color continuity detector：完成，synthetic acceptance `5/5`，commit `f4af546`。
- M3.3.1 benchmark contract：完成，commit `fd06975`。
- M3.3.1 manifest validator：完成，commit `5151060`。
- M3.3.1 report-only evaluator：本地完成，commit `57b35b8`；远程是否包含该提交必须用 `git rev-parse origin/main` 核对。
- M4.0 deterministic local search：完成，commit `74d9a77`。
- M4.0 query regression：完成，commit `8eb0fa9`。
- 最新已知远程基线：`637cf99`；不要在未核对远程前声称 `57b35b8` 已推送。
- 已知验证：视频 `78/78`、搜索 `10/10`、benchmark validator `9/9`、benchmark evaluator `8/8`。
- `schemas/item.schema.json` 是 frozen schema，未经架构决策不得修改。
- 真实用户视频泛化和人工标注尚未开始。

## 架构边界

1. `item.json` 是事实来源；`indexes/` 是可重建派生数据。
2. ingest 只生成骨架和队列；分析独立消费队列。
3. 所有 ffmpeg/ffprobe 调用必须封装在 `FfmpegAdapter` 内。
4. synthetic acceptance 与真实视频 benchmark 必须隔离。
5. benchmark evaluator 只生成 report，不接入 milestone acceptance，不写回 item/index。
6. 缺失媒体、不完整标注、低置信度、candidate 或 unknown 不能伪造成事实或指标。
7. M4.0 保持本地、确定性、可解释、稳定排序。
8. 暂不进入 M3.4、M4.1、PWA、embedding、向量数据库、云端检索或 Style DNA 完成。
9. 中文同义词和自然语言语义扩展是 M4.0 当前边界，不要当作确定性 bug 擅自修改。

## 手机 OpenMinis 与电脑 TRAE

### OpenMinis/iPhone 适合

- 架构讨论、代码审查和明确边界的中小型实现
- Python、ffmpeg 小规模验证和单元测试
- benchmark validator/evaluator 的空数据、metadata-only 和错误路径
- 文档、handoff、回归测试、Git commit 和远程核验

### TRAE/电脑适合

- 真实视频、逐帧检查、人工标注和批量评估
- 长视频、大量媒体、持续 CPU/内存/磁盘任务
- 可视化时间轴调试
- OpenCV、PyTorch、TensorFlow 等复杂依赖
- 大规模跨模块重构、IDE 导航、多分支和 PR 工作

命中上述 TRAE 条件时停止手机端扩展，记录当前 commit、未提交修改、测试、失败原因和恢复命令，不要提交半成品。

## Git 与安全规约

- 不使用 `git reset --hard` 或破坏性 checkout。
- 修改前后运行相关测试、`python3 -m py_compile` 和 `git diff --check`。
- 每个逻辑阶段单独提交，提交信息使用 `feat:`、`fix:`、`docs:`、`test:` 等前缀。
- 网络 push 最多尝试一次；失败后不循环重试，记录远程基线并等待网络或切换 TRAE。
- `GITHUB_TOKEN` 等秘密只通过环境变量名引用，绝不打印、写文件、写入 remote URL 或提交。
- 不提交真实视频、帧、临时日志、个人路径、凭据或任务提示词。
- 修改仓库内 skill 后，按 `AGENTS.md` 要求同步到 `/var/minis/skills/`。

## 目录和数据

```text
items/       素材目录；source 文件不入 Git，item.json 是事实
indexes/     可重建派生索引
skills/      仓库内权威 Skill 实现和测试
schemas/     frozen schema；未来扩展只能先放 schemas/drafts/
configs/     版本化配置、fixture 和 benchmark manifest
scripts/     项目脚本（若存在）
docs/        架构、设计、handoff 和开发文档
```

`item.json` 保存素材类型、来源、分析版本、分析状态、视觉特征和语义分析；标签采用 `维度:值` 格式。原始媒体、视频帧和隐私素材遵循 `.gitignore`，不进入公开仓库。

## 推荐汇报格式

Agent 完成阶段、提交、推送失败、测试失败或停止时，使用一个单独 Markdown 代码块汇报：

```text
【交给架构师】
阶段：
本轮完成：
本地 HEAD：
远程 HEAD：
提交 SHA：
是否已推送：
工作区状态：
修改文件：
测试命令与结果：
真实运行验证：
未验证事项：
阻塞原因：
是否需要架构决策：
是否建议切换 TRAE：
切换 TRAE 的原因：
给 TRAE 的恢复任务：
下一步唯一建议：
```

不要输出完整代码、完整 diff、完整日志或任何秘密。

## 深入文档

- `PROJECT.md`：产品定义、目录和里程碑总览
- `ARCHITECTURE.md`：完整系统架构
- `docs/ARCHITECTURE_CONTEXT.md`：可迁移的用户环境和 Agent 协作上下文
- `docs/AGENT_HANDOFF_M3.md`：当前真实交接状态
- `docs/PROJECT_CONTEXT.md`：详细项目上下文
- `docs/DESIGN-M3.3.1-generalization-benchmark.md`：真实视频 benchmark 契约
- `docs/DESIGN-M4-minimal-search.md`：M4.0 检索契约
- `CHANGELOG.md`：变更历史
