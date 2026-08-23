---
name: stylevault-search
version: 0.1.0
description: >-
  StyleVault M4.0 本地确定性检索。基于 item.json 的标签、summary、editing_rules、
  preference、collection 和 type，输出可解释、稳定排序的 JSON 结果。不使用 embedding、
  向量数据库、云端服务或 Style DNA。
---

# StyleVault Search

## Contract

- `items/*/item.json` 是唯一事实来源；`indexes/tags.json` 是可重建索引，不能成为唯一事实来源。
- 默认检索 `analysis.status` 为 `done` 或 `needs_review` 的条目；pending/error 条目不进入结果。
- `--tag`/`--tags` 做精确标签匹配；`--mode and` 要求全部命中，`--mode or` 命中任一。
- `--type`、`--collection`、`--preference-min` 是过滤条件。
- `--text` 对标签、summary 和 editing_rules 做确定性 token 匹配。
- preference 只做过滤和轻量排序，不能压过标签命中。
- 结果按 `score` 降序，再按 `item_id` 升序稳定排序；同一 item 只出现一次。
- 只读 item.json，不修改 item.json、tags.json 或其他索引。

## Score

```text
score = 5.0 * matched_tag_ratio
      + 1.5 * matched_rule_ratio
      + 1.0 * matched_summary_ratio
      + 0.2 * normalized_preference
```

文本匹配是 token 的不区分大小写子串匹配；中文按空白切分，连续中文短语也作为整体 token。每个字段最多贡献一次比例分。结果包含命中字段和命中 token，便于审计。

`--preference-min` 接受 0-1 归一化阈值；实际 preference 为 1-5，按 `preference / 5` 比较。也接受大于 1 的 1-5 原始分值以兼容本地调用。

## CLI

```bash
python3 scripts/search.py --tag style:cyberpunk
python3 scripts/search.py --tags style:cyberpunk,color:neon --mode and
python3 scripts/search.py --type image --collection golden-dataset
python3 scripts/search.py --preference-min 0.7
python3 scripts/search.py --text "低饱和 夜景"
```

Output is JSON with query, count, results, and `index_used` metadata. No network or embedding calls are made.
