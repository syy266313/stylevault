---
name: stylevault-ingest
version: 1.0.0
description: >-
  StyleVault 采集入口 (M1)。把素材（图片/视频/网页）导入个人视觉审美知识库：
  附件、apple-photos 相册、URL 网页三通道；SHA-1 去重（重复素材只追加来源引用，
  不建新条目）；采集与分析解耦——只生成 item.json 骨架并进入分析队列
  (analysis.status=pending)，不执行视觉分析（由 stylevault-analyze-image 消费）。
  Trigger: 用户说"收藏这个/存进 StyleVault/入库/导入素材"或提交图片视频 URL 时。
---

# StyleVault Ingest (采集与落盘)

## 工作流

1. **确认来源通道**（三选一）：
   - 附件/本地文件 → `python3 scripts/ingest.py <path> [--note "备注"]`
     （默认 origin=attachment；手动导入用 `--origin import`）
   - apple-photos → 先 `python3 scripts/ingest.py --list-photos` 列最近 20 条，
     再 `--photos N` 导入指定序号（不带 N 默认导入第 1 条）
   - URL/网页 → `python3 scripts/ingest.py --url <url> [--full-page] [--note "备注"]`
2. **执行并解读结果**：输出 JSON 含 `result: created|duplicate`。
   - `created` → 已落盘 `items/<id>/`，分析已入队；
   - `duplicate` → 素材已存在（SHA-1 命中），仅追加了来源引用，**不要重复分析**。
3. **交付反馈**：告知用户入库结果与条目 ID；分析由 M2 skill 消费队列完成，
   当前不等待。可选 `--queue` 查看待分析队列。

## 规则与细节

- **去重**：SHA-1 全量比对（跨天也能识别）。重复素材不建新目录，`source.refs`
  追加一条 `{origin, path, url, note, at}`。
- **ID 规则**：`sv_YYYYMMDD_<sha1 前 8 位>`；同日同文件导入会命中同目录，
  跨日由全量扫描兜底。
- **骨架字段**：必填 id/type/source/file/created_at/analyze_version/analysis 齐备，
  `analysis.status=pending`、`embedding.status=none`、`pipeline_log` 记 ingest 事件。
  `analyze_version` 从 `configs/pipeline.json` 读取，保证与当前管线一致。
- **类型判定**：按扩展名 image（jpg/png/gif/webp/heic…）| video（mp4/mov/mkv…）；
  不支持的类型拒绝并提示。
- **队列**：`indexes/queue.json`（派生数据，可重建）。分析 skill 消费后移除条目。
- **网页采集**：经 minis-browser-use 导航+整页/视口截图，落盘 `source.png`，
  `source.url` 记录原链接、`source.title` 记录页面标题。
- **环境变量**：`STYLEVAULT_ROOT` 可覆盖 vault 根目录（默认
  `/var/minis/shared/stylevault`）。

## 验收自测

```
# 附件（首导入 → created）
python3 scripts/ingest.py test.png --note "测试"
# 附件（同文件再导入 → duplicate + refs 追加）
python3 scripts/ingest.py test.png --note "第二次"
# 相册
python3 scripts/ingest.py --photos 1
# URL
python3 scripts/ingest.py --url https://example.com
# 队列
python3 scripts/ingest.py --queue
```

## 边界

- 本 skill 不做分析（M2）；不处理视频抽帧（M3）；不做网页正文抓取（可选扩展）。
- 重复导入的 refs 追加是唯一会改写已存在 item.json 的场景，追加后不触碰 analysis。
