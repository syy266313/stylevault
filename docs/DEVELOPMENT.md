# StyleVault 开发指南

## 环境

| 依赖 | 用途 | 安装 |
|---|---|---|
| python3 + py3-pillow | 分析脚本 / 图像特征 | `apk add python3 py3-pillow` |
| libheif-tools | HEIC → JPEG 转码 | `apk add libheif-tools` |
| ffmpeg | M3 视频切分/抽帧 | `apk add ffmpeg`（M3 前安装） |
| apple-vision / apple-photos / browser_use | 本地视觉 / 相册 / 网页采集 | 内置 |

## 目录约定

```
shared/stylevault/          ← Git 仓库根（本地优先，文件即数据库）
├── items/<id>/             ← 素材（source 不入 git，item.json 入 git）
├── indexes/                ← 派生索引（可重建）
├── skills/stylevault-*/    ← skill 代码唯一事实源（同步到 /var/minis/skills/）
├── schemas/                ← JSON Schema（v1 冻结，drafts/ 放 v2 草案）
├── configs/                ← 标签本体 / 管线配置 / golden 基准
└── docs/                   ← 设计与开发文档
```

## Git 工作流（持续集成）

1. 每个功能模块完成 → 更新 `PROJECT.md` + `CHANGELOG.md`
2. `git add . && git commit`（规范前缀：`feat:` `fix:` `refactor:` `docs:` `test:` `chore:`）
3. `git push https://syy266313:${GITHUB_TOKEN}@github.com/syy266313/stylevault.git main`
   （remote origin 无 token 明文；tag/分支用同一方式推送）

版本策略：
- 里程碑完成 → `git tag -a vX.Y.Z` + `git branch release/vX.Y`（冻结）
- 冻结后 schema 变更走 `schemas/drafts/` 草案，不修改冻结版

## Skill 代码同步

仓库 `skills/stylevault-*` 是唯一事实源，修改后同步到运行位置：

```bash
cp -r skills/stylevault-* /var/minis/skills/
```

## 分析管线速查

```bash
# 采集（M1）
python3 /var/minis/skills/stylevault-ingest/scripts/ingest.py <file> [--note ...]
python3 /var/minis/skills/stylevault-ingest/scripts/ingest.py --url <url>
python3 /var/minis/skills/stylevault-ingest/scripts/ingest.py --list-photos / --photos N

# 分析（M2/M2.5，需 API 配置）
python3 /var/minis/skills/stylevault-analyze-image/scripts/analyze.py phase-a queue   # 本地特征
python3 /var/minis/skills/stylevault-analyze-image/scripts/analyze.py phase-b queue   # 视觉模型
python3 /var/minis/skills/stylevault-analyze-image/scripts/analyze.py rebuild-index
```

API 配置（环境变量，可切换）：`STYLEVAULT_MODEL`（默认 gpt-5.6-terra）/ `OPENAI_BASE_URL` / `OPENAI_API_KEY`。
CLI 覆盖：`--model --base-url --api-key`。

## 测试

- 单元测试：`python3 -m py_compile <script>` + 内嵌断言（见各脚本尾部注释）
- 验收自测：各 SKILL.md 的「验收自测」节
- Golden 基准：`configs/golden-dataset.json`（20 张 ground truth），A/B 用 `ab_test.py`

## 环境变量（敏感，勿回显）

- `GITHUB_TOKEN`：GitHub 推送
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `STYLEVAULT_MODEL`：Phase B 视觉分析
