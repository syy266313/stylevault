# StyleVault

个人视觉审美知识库 · 本地优先 · 文件即数据库

用户收藏图片/视频/网页案例，AI 自动分析构图、色彩、光影、镜头语言、剪辑节奏、风格标签，形成可检索的审美知识资产。未来以此辅助 AI 自动剪辑。

## 目录结构

```
stylevault/
├── items/          # 素材库：每个素材一个独立文件夹
│   └── <sv_YYYYMMDD_hash8>/
│       ├── source.xxx     # 原始文件（网页条目为 snapshot.png + source.url）
│       ├── frames/        # 视频关键帧（视频条目）
│       └── item.json      # 元数据 sidecar（JSON 是事实来源）
├── indexes/        # 派生索引（可重建，非事实来源）
│   └── tags.json          # 标签聚合索引
├── skills/         # 项目自定义 Skill 规划说明（实际安装到 /var/minis/skills/）
├── schemas/        # 数据规范
│   ├── item.schema.json   # item.json JSON Schema（v1）
│   └── example.item.json  # 完整示例
├── configs/        # 配置（版本化，可重放）
│   ├── tag-ontology.json  # 六维标签本体
│   ├── pipeline.json      # 分析管线版本配置
│   └── golden-dataset.json# M2.5 Golden 基准（20 张 ground truth）
├── docs/           # 设计与开发文档（v0.4 冻结后新增）
│   ├── DEVELOPMENT.md                  # 开发指南
│   ├── DESIGN-style-embedding.md       # style_embedding 设计
│   ├── DESIGN-rhythm-v2.md             # rhythm 参数化设计
│   └── DESIGN-M3-video-language-engine.md  # M3 视频风格建模
└── README.md
```

## 核心原则

1. **本地优先**：全部数据在本目录，零云依赖。
2. **文件即数据库**：无数据库，目录 + JSON 即事实。
3. **JSON 是事实来源**：item.json 完整描述一个素材；indexes/ 可随时重建。
4. **版本化可重放**：`analyze_version` + `pipeline_log` 记录每次分析；升级管线后旧条目重放即可，数据不报废。

## item.json 要点

- 必填：`id` / `type` / `source` / `file` / `created_at` / `analyze_version` / `analysis`
- 分析维度（统一结构 `{tags, summary, confidence}`）：subject 主题 / style 风格 / mood 情绪 / color 色彩 / composition 构图 / lighting 光线 / camera 摄影语言 / rhythm 节奏（视频专属）
- `analysis.model` 记录产生分析的模型与版本；`analysis.status` = pending | done | error | needs_review
- `preference`：个人偏好评分 1-5
- `vision`：本地确定性特征快照（apple-vision + pillow），与 LLM 语义分析分离
- 标签格式统一 `维度:值`（如 `composition:rule-of-thirds`），取值见 configs/tag-ontology.json

## 状态

- 架构：v0.2 定稿（ARCHITECTURE.md）
- M0 基建：✅ 完成（目录 + Schema + 配置 + 能力盘点）
- M1 采集存储：进行中（stylevault-ingest skill）

## 能力复用（不重复开发）

- apple-vision：内容识别/人脸/相似度/快速分析
- apple-photos：相册素材导入
- browser_use：网页案例采集
- skill-creator：新 skill 遵循其规范
- pdf-reader PWA 工程模式：前端复用（SW/IndexedDB/minis:// 交付）
