# StyleVault

个人视觉审美知识库 · 本地优先 · 文件即数据库

用户收藏图片/视频/网页案例，AI 自动分析构图、色彩、光影、镜头语言、剪辑节奏、风格标签，形成可检索的审美知识资产。未来以此辅助 AI 自动剪辑。

- 远程仓库：https://github.com/syy266313/stylevault
- 架构文档：[ARCHITECTURE.md](./ARCHITECTURE.md)
- 数据 Schema：[schemas/item.schema.json](./schemas/item.schema.json)

## 核心原则

1. **本地优先**：数据在 `items/`，零云依赖。
2. **文件即数据库**：目录 + JSON 即事实，无数据库。
3. **JSON 是事实来源**：item.json 完整描述素材；`indexes/` 可随时重建。
4. **版本化可重放**：`analyze_version` + `pipeline_log` 记录每次分析；升级管线后重放不报废。
5. **采集与分析解耦**：ingest 只产骨架（status=pending）入队；analyze 消费队列。

## 目录结构

```
stylevault/
├── items/          # 素材库（source 文件不入 git，item.json 入 git）
│   └── <sv_YYYYMMDD_hash8>/  source.xxx + item.json
├── indexes/        # 派生索引（tags.json / queue.json，可重建）
├── skills/         # 自定义 Skill 规划说明
├── schemas/        # item.schema.json + example
├── configs/        # tag-ontology.json / pipeline.json
├── PROJECT.md      # 本文件（项目状态）
└── CHANGELOG.md    # 变更记录
```

## Milestone 进度

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 基建 | 目录骨架 + Schema + 配置 + 能力盘点 | ✅ 完成 |
| M1 采集存储 | stylevault-ingest（三入口 + SHA-1 去重 + 分析队列） | ✅ 完成 |
| M2 图片分析 | stylevault-analyze-image（本地特征 + 语义分析） | ✅ 完成 |
| M2.5 质量校准 | editing_rules + Golden Dataset(20 张) + gpt-5.6-terra 视觉管线 | ✅ 完成（20/20 全量分析） |
| M3 视频分析 | video analysis scaffold + test suite + FfmpegAdapter probe/segment | 🔨 M3.1.1 已完成，M3.2 fixture 基础已建立，帧级检测待实现 |
| M4 检索+UI | stylevault-search + PWA 画廊 | ⬜ 未开始 |
| M5 知识问答 | 基于知识库的问答 | ⬜ 未开始 |
| M6 剪辑辅助 | 知识库辅助 AI 剪辑（未来） | ⬜ 规划中 |

## 开发约定

- **Git 工作流**：功能模块完成 → 更新 PROJECT.md + CHANGELOG.md → `git add .` → commit → push。
- **提交规范**：`feat:` 新功能 / `fix:` 修复 / `refactor:` 重构 / `docs:` 文档 / `test:` 测试 / `chore:` 维护。
- **Skills 安装位置**：`/var/minis/skills/stylevault-*`（遵循 skill-creator 规范）。
- **素材不入库**：`items/*/source.*` 在 .gitignore，只版本化元数据。
