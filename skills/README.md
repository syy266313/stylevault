# StyleVault 自定义 Skills 规划

实际 Skill 安装位置：`/var/minis/skills/stylevault-<name>/`（遵循 skill-creator 规范：YAML frontmatter + Workflow + scripts/）。
本目录是 **skill 代码的唯一事实源（Git 版本化）**：代码修改后需同步到运行位置：

```
# 同步（仓库 → 运行位置）
cp -r skills/stylevault-* /var/minis/skills/
```

## 需要自定义开发的 Skill 清单

| Skill | 阶段 | 职责 | 主要工具 | 复用 |
|---|---|---|---|---|
| `stylevault-ingest` | **M1** | 采集落盘：接收素材 → 归一化 → 生成 item.json 骨架 → 写 pipeline_log | shell、browser_use、apple-photos export | 无前置 |
| `stylevault-analyze-image` | M2 | 图片两级分析：本地特征(Phase A) + LLM 语义(Phase B) → 写 analysis | apple-vision、py3-pillow、LLM | ingest 产物 |
| `stylevault-analyze-video` | M3.0 | 视频风格建模骨架：统一 adapter、mock、rhythm.params、style_dna 合并 | ffmpeg（后置）、python3 | analyze-image / mock |
| `stylevault-tag` | M2 | 标签本体维护 + 重建 indexes/tags.json 聚合索引 | python3 | configs/tag-ontology.json |
| `stylevault-search` | M4 | 标签/关键词/相似度检索 + 知识库问答 | python3、apple-vision similarity、LLM | indexes/tags.json |

## 不需要开发的（已存在）

| 能力 | 现成工具 | 说明 |
|---|---|---|
| 文件系统 | shell（iSH） | 读/写/移动/备份，无需 filesystem MCP |
| 相册 | apple-photos | list/albums/export/import |
| 本地视觉 | apple-vision | ocr/classify/faces/similarity/analyze/overlap |
| 网页采集 | browser_use | 截图/取文本/抓资源 |
| 浏览器环境 | browser_use + minis-browser-use CLI | 批量流程可脚本化 |
| PWA 前端工程 | pdf-reader 模式 | SW/IndexedDB/minis:// 交付，直接复用 |
| Skill 开发规范 | skill-creator | 新 skill 遵循其规范 |

## M1 里程碑（stylevault-ingest）— ✅ 已完成

- [x] 三入口（附件 / 相册 / URL-网页）都能落盘并生成符合 schema 的 item.json 骨架
- [x] id 生成规则：sv_YYYYMMDD_<sha1 前 8 位>
- [x] SHA-1 去重：重复素材不建新条目，仅追加 source.refs
- [x] 采集与分析解耦：骨架 analysis.status=pending，入 indexes/queue.json 队列
- [x] 网页采集：minis-browser-use 导航+截图，source.url/title 记录
- [x] 视频原片可直接导入（抽帧留 M3）

用法速查：
```
python3 /var/minis/skills/stylevault-ingest/scripts/ingest.py <file> [--note]
python3 /var/minis/skills/stylevault-ingest/scripts/ingest.py --list-photos
python3 /var/minis/skills/stylevault-ingest/scripts/ingest.py --photos N
python3 /var/minis/skills/stylevault-ingest/scripts/ingest.py --url <url> [--full-page]
python3 /var/minis/skills/stylevault-ingest/scripts/ingest.py --queue
```

## 下一步：M2 分析

- [ ] stylevault-analyze-image：消费 queue，Phase A（apple-vision + pillow）→ Phase B（LLM 语义 JSON）
- [ ] stylevault-tag：重建 indexes/tags.json 聚合索引
