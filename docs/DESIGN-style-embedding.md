# style_embedding 字段设计（v2 草案）

> 目标：为 StyleVault 提供语义向量嵌入能力——相似案例检索（M4）、风格聚类、Style DNA 跨素材比对的基础。
> 状态：设计文档（v1.0）。字段在 v1 已预留骨架，v2 细化并启用。

## 1. 动机

当前检索能力：标签精确匹配（`indexes/tags.json`）+ `apple-vision similarity`（像素级相似）。
局限：① 语义相近但标签不同（"赛博朋克" vs "霓虹夜景"）检索不到；② 像素相似 ≠ 风格相似；
③ 无法做"多素材风格距离"这类计算。

style_embedding 把每个条目的**风格语义**压成向量，支持余弦相似度检索与聚类。

## 2. 字段设计（顶层 `embedding`，v2 完整形态）

```jsonc
{
  "embedding": {
    "status": "done",              // none(未启用) | pending | done | error
    "kind": "analysis",            // analysis(推荐) | image | hybrid
    "model": "text-embedding-3",   // 嵌入模型名（可切换，环境变量配置）
    "version": "2026-08",          // 模型版本
    "dimensions": 1024,
    "vector": [0.0012, -0.0034, ...],
    "source_text": "subject:cyberpunk style:cyberpunk ... 一句话总评 ...",  // 序列化摘要（调试/审计）
    "created_at": "2026-08-15T17:00:00+08:00"
  }
}
```

v1 已冻结字段（status/model/version/dimensions/vector）语义不变；**新增**：`kind` / `source_text` / `created_at`。

## 3. 生成策略（两路，推荐 analysis 为主）

| 方案 | 输入 | 特点 | 决策 |
|---|---|---|---|
| **A. analysis 嵌入**（推荐） | 序列化 `analysis`（八维标签 + summary + editing_rules 关键参数）→ 文本嵌入 | 成本低、可重放、与标签体系语义一致、不依赖图像模型 | ✅ V2 默认 |
| B. 图像嵌入 | 图片 → 多模态嵌入模型 → 向量 | 捕捉像素级内容，成本高 | 增强项（M4 视需要） |
| C. hybrid | A + B 拼接/加权 | 最全，成本最高 | 远期 |

方案 A 细节：
- `source_text` 序列化规则：`维度:标签 维度:标签 ... | summary | editing_rules[aspect:rule]`
- 嵌入模型：OpenAI 兼容 `embeddings` 端点（`/embeddings`），模型经环境变量 `STYLEVAULT_EMBED_MODEL` 配置（不写死）
- 幂等：`analysis` 未变则跳过；`--force` 重生成

## 4. 管线接入（v2 实现计划）

```
analyze phase-b 完成 (status=done)
  → embed 队列（indexes/embed-queue.json，派生可重建）
  → embed.py: 序列化 → /embeddings → 写 embedding 字段
  → M4: indexes/embeddings.json（{item_id: {vector, model, dims}} 或 sqlite-vec）
  → 检索: 查询向量 → 余弦 top-k；apple-vision similarity 作为像素级补充
```

## 5. 与 Style DNA 的关系

style_embedding 是 Style DNA 的**可计算形式**（向量），Style DNA 是其**可读形式**（JSON 结构化）。
M3 完成后：`style_dna`（结构化）→ 序列化 → embedding（向量）→ 支持"找风格相近的 3 个案例"。

## 6. Schema 草案

见 `schemas/drafts/item.schema.v2.draft.json`（embedding 完整字段 + rhythm 参数化 + style_dna 预留）。
