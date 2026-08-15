# StyleVault 架构设计 v0.1

> 个人视觉审美知识库 · 架构文档
> 日期：2026-08-11 · 状态：v0.2 定稿（M0 基建已完成，见 schemas/ 与 configs/）

---

## 0. 产品定义

**StyleVault = 个人视觉审美知识库。**

用户收藏优秀图片、视频、网页案例；系统自动分析出**构图、色彩、光影、镜头语言、剪辑节奏、风格标签**六类结构化特征；形成可检索、可对比、可调用的审美知识资产。未来以此知识库为"风格约束源"，辅助 AI 自动剪辑。

核心价值主张：
1. 把"凭感觉收藏"变成"结构化知识"——收藏夹从吃灰变为可检索资产；
2. 从"看案例"到"用案例"——检索即灵感的参考库；
3. 知识库是未来剪辑引擎的风格大脑（镜头选择、节奏匹配、调色参考的依据）。

## 1. 系统架构

五层架构，本地优先，数据全部留在设备内。

```
┌──────────────────────────────────────────────────────────┐
│ L5 应用层   StyleVault PWA（画廊/检索/对比）               │
│             └ 未来：剪辑工作台（读知识库出剪辑建议）        │
├──────────────────────────────────────────────────────────┤
│ L4 服务层   OpenMinis Agent 编排（流水线调度/重试/幂等）    │
├──────────────────────────────────────────────────────────┤
│ L3 分析层   本地确定性分析（apple-vision / ffmpeg / pillow）│
│             + LLM 语义分析（构图/色彩情绪/镜头语言/标签）    │
├──────────────────────────────────────────────────────────┤
│ L2 存储层   原始文件 + sidecar 元数据(item.json) + 索引     │
├──────────────────────────────────────────────────────────┤
│ L1 采集层   附件/相册/网页/URL 四通道入口                   │
└──────────────────────────────────────────────────────────┘
```

各层职责与关键决策：

| 层 | 职责 | 关键决策 |
|---|---|---|
| L1 采集 | 接收素材并归一化（图片/视频/网页三种类型判定） | 网页案例存"截图+URL+标题"，不存整站 |
| L2 存储 | 文件与元数据分离；sidecar JSON 与文件共存 | 备份/迁移=拷目录；无数据库依赖 |
| L3 分析 | **两级分析**：本地确定性特征 + LLM 语义理解 | 确定性用框架免费即时；语义按需调 LLM |
| L4 服务 | 编排流水线，维护上下文，失败重试 | 分析幂等可重放，pipeline 版本化 |
| L5 应用 | PWA 画廊，复用 pdf-reader 工程模式 | IndexedDB+SW，离线可用，minis:// 交付 |

**核心设计原则：**
1. **原始文件与元数据分离**：`vault/items/<id>/` 下 `source.ext` + `item.json`（sidecar），拷目录即备份/迁移。
2. **两级分析**：颜色直方图、人脸、相似度等确定性特征用本地框架（免费、快、离线）；构图语言、色彩情绪、风格标签等语义理解交给 LLM（结构化 JSON 输出）。
3. **分析可重放**：item.json 记录 `analyze_version`，升级分析器后可全量重放，旧数据不报废。
4. **本地优先**：全部数据在 `/var/minis/shared/stylevault/`，零云依赖（与 pdf-reader 同一哲学）。

## 2. 技术栈

环境约束：iSH / Alpine Linux aarch64（musl），pip 装 C 扩展易失败 → **一律用 apk 原生包**。

| 层 | 选型 | 说明 |
|---|---|---|
| 编排 | OpenMinis Agent + Skills | 已在运行，工具链完整 |
| 本地视觉 | `apple-vision`（Vision framework） | classify/faces/similarity/analyze 原生、免费、离线 |
| 视频处理 | `ffmpeg`（apk add） | 抽帧、场景切分、镜头时长统计 |
| 语义分析 | 默认 LLM（经 agent 调用） | 构图/色彩情绪/镜头语言/风格标签 |
| 图像统计 | `py3-pillow`、`py3-numpy` | 主色调、亮度、饱和度、三分线构图检测 |
| 存储 | 文件系统 JSON / JSONL | V1 条目量级无需数据库 |
| 检索 | V1：标签+关键词+`apple-vision similarity`；V2：sqlite FTS5 / 向量 | 渐进式 |
| 前端 | 纯静态 PWA（HTML+JS+IndexedDB+SW） | 复用 pdf-reader 模式，零框架 |
| 网页采集 | `browser_use` + `fetch` | 截图、正文、链接 |
| 视频下载 | `yt-dlp`（未来） | 视频案例采集 |

**复用清单（V1 全部零新增外部依赖）：**
- ✅ `apple-vision`：内容识别、人脸、相似度、快速预览分析
- ✅ `apple-photos`：相册素材导入
- ✅ `browser_use`：网页案例采集
- ✅ pdf-reader 的 PWA 工程模式：SW 缓存、IndexedDB、minis:// 交付、离线优先
- ✅ `skill-creator` 规范：新 skills 遵循其结构（frontmatter + Workflow + scripts/）
- ✅ `minis-model-use`：未来可插专用视觉模型做深度分析

**需新增：** 仅 `ffmpeg`（`apk add ffmpeg`，视频分析前置）。

## 3. OpenMinis Agent 工作流

### 触发方式（三种）
1. **即时收藏**：用户丢文件/URL，说"收藏这个" → 单条采集+分析；
2. **批量分析**：用户说"分析新入库的" → 扫描无 analysis 的条目批量跑；
3. **知识检索**：用户问"库里有没有 XX 风格案例" → 走检索。

### 主流水线（一次收藏的完整生命周期）

```
[采集 L1]  输入归一化 → 判定 type(image|video|webpage) → 落盘 vault/items/<id>/
           └ 网页：browser_use 全页截图 + 抓标题/URL/正文摘要
[规范化]   生成 item.json 骨架（来源/时间/媒体信息: 尺寸/时长/MIME）
[分析A]   本地确定性特征
           ├ image   : apple-vision analyze(classify+faces) + pillow 主色调/亮度/饱和度
           ├ video   : ffmpeg 抽代表帧 + 场景切分(scdet) + 镜头时长统计 → 帧走图片分析
           └ webpage : 页面截图按 image 处理
[分析B]   LLM 语义分析（提示词内嵌 item.json + 帧路径）
           输出严格 JSON：构图/色彩/光影/镜头语言/剪辑节奏/风格标签(带置信度)
[入库]    写 analysis 到 item.json → 更新 tags.json 聚合索引
[质检]    置信度 < 阈值 的标签标记 `needs_review`，不阻塞入库
```

### Agent 角色定位
- **流水线调度者**：逐步调用 skill（skill 内部封装工具脚本），维护上下文；
- **容错**：LLM 输出 JSON 非法 → 重试 1 次 + schema 校验；失败条目留 `status:error` 不阻塞批量；
- **幂等**：item.json 已有 analysis 且版本一致 → 跳过；支持 `--force` 重放；
- **渐进反馈**：先出本地特征（快），再补语义分析（慢），用户可随时看进度。

## 4. Skills 设计

目录结构遵循 skill-creator 规范：`/var/minis/skills/stylevault-<name>/SKILL.md` + `scripts/`。

| Skill | 职责 | 主要工具 |
|---|---|---|
| `stylevault-ingest` | 采集、落盘、规范化，生成 item.json 骨架 | shell、browser_use、apple-photos export |
| `stylevault-analyze-image` | 图片两级分析（本地特征 + LLM 语义） | apple-vision、py3-pillow、LLM |
| `stylevault-analyze-video` | 视频抽帧/场景切分/节奏统计 + 帧分析 | ffmpeg、apple-vision、LLM |
| `stylevault-tag` | 标签本体管理 + tags.json 聚合索引 | python3 |
| `stylevault-search` | 标签/关键词/相似度检索 + 知识库问答 | python3、apple-vision similarity、LLM |

每个 skill 内含：SKILL.md（触发词 + Workflow + 细节）+ scripts/（可复用脚本）+ 自测用例。

### 风格标签本体（stylevault-tag 核心资产）

六维标签体系，格式 `维度:值`，避免歧义：

| 维度 | 示例值 |
|---|---|
| 风格 style | cinematic / minimal / cyberpunk / film / neo-chinese / documentary… |
| 情绪 mood | calm / warm / tense / nostalgic / energetic… |
| 色彩 color | warm / cool / high-sat / desaturated / teal-orange / mono… |
| 构图 composition | rule-of-thirds / symmetry / frame-in-frame / leading-line / negative-space… |
| 光影 lighting | hard / soft / rim / backlight / low-key / golden-hour… |
| 镜头 camera | close-up / wide / low-angle / tracking / handheld / 50mm-look… |
| 节奏 rhythm（视频） | fast-cut / long-take / match-cut / j-cut / steady… |

每条标签带 `confidence` + `source`（pipeline 版本），低置信度标记 `needs_review`。

## 5. MCP 需求

**平台现实**：Minis 已内置大量"MCP 级"能力（apple-* 工具、browser_use、文件系统），**V1 不需要任何外部 MCP server**——这是最大的复用。

| 传统 MCP 需求 | 现状 | 决策 |
|---|---|---|
| filesystem MCP | ✅ shell 直接可用 | 不引入 |
| photos MCP | ✅ apple-photos | 不引入 |
| vision MCP | ✅ apple-vision | 不引入 |
| browser MCP | ✅ browser_use | 不引入 |
| 视频下载 | ❌ | V2：yt-dlp（apk/二进制） |
| 向量检索 | ❌ | V2：sqlite-vec / 本地 embedding |
| 网页完整归档 | ❌ | V2：single-file 式快照 |

**结论**：V1 零新增 MCP；V2 按需评估 yt-dlp 与本地向量检索。若未来 StyleVault 部署到桌面端 OpenMinis 环境，再考虑接入 Notion/素材库类 MCP 作为采集通道。

## 6. 数据结构

### 目录布局

```
/var/minis/shared/stylevault/
├── vault.json          # 库级元数据（schema 版本、统计、最近分析时间）
├── tags.json           # 标签聚合索引（派生数据，可重建，非事实源）
└── items/
    └── <item_id>/      # item_id = 时间戳 + 内容 hash 短码
        ├── source.jpg  # 原始文件（网页条目为 snapshot.png + source.url）
        ├── frames/     # 视频关键帧（视频条目）
        └── item.json   # 完整元数据（sidecar）
```

### item.json Schema

```jsonc
{
  "id": "sv_20260811_ab12cd",
  "type": "image | video | webpage",
  "source": {
    "origin": "attachment | photos | browser | url | import",
    "url": "https://...",          // 网页/URL 来源
    "album": "灵感",               // 来自相册时
    "note": "用户备注"
  },
  "file": {
    "path": "items/sv_xxx/source.jpg",
    "mime": "image/jpeg",
    "size": 245678,
    "width": 1920, "height": 1080,
    "duration_ms": 0               // 视频才有
  },
  "captured_at": "2026-08-11T15:00:00+08:00",
  "pipeline": { "analyze_version": "v1", "analyzed_at": "...", "status": "done" },

  "vision": {                       // Phase A：本地确定性特征
    "classifications": [{"label": "person", "confidence": 0.92}],
    "faces": [{"count": 1, "rect": [..]}],
    "palette": [{"hex": "#1a1a2e", "ratio": 0.42}, ...],   // 主色 Top5
    "brightness": 0.31, "saturation": 0.55
  },

  "semantic": {                     // Phase B：LLM 语义
    "composition":  {"summary": "三分法构图，主体置于右三分线", "tags": ["rule-of-thirds"], "confidence": 0.9},
    "color":        {"mood": "cool-cinematic", "tags": ["teal-orange"], "confidence": 0.85},
    "lighting":     {"tags": ["rim-light"], "confidence": 0.8},
    "camera":       {"tags": ["low-angle", "wide"], "confidence": 0.75},
    "editing":      {"tags": ["fast-cut"], "avg_shot_ms": 1800},   // 视频专属
    "style_tags":   [{"tag": "cinematic", "confidence": 0.95}],
    "summary": "一句话点评：低机位+轮廓光强化主体，赛博朋克质感"
  },

  "collections": ["portrait-moodboard", "teal-orange"]
}
```

### 设计要点
- **sidecar JSON 与文件共存** → 备份/迁移/版本管理极简；
- **tags.json 是可重建的派生索引**，不是事实源，坏了重扫即可；
- **视频条目保留关键帧**（frames/），让检索层可以"看图说话"；
- **analyze_version 支撑升级重放**：新分析器上线后旧条目自动标记待重放。

## 7. V1 开发路线

里程碑式交付，每个 M 都可验收：

| 里程碑 | 内容 | 工作量 | 验收标准 |
|---|---|---|---|
| **M0 基建** | 装 ffmpeg；建 vault 目录结构；本架构定稿 | 0.5 天 | 目录就绪、依赖可跑 |
| **M1 采集存储** | `stylevault-ingest` skill；附件/相册/URL 三入口落盘 | 1 天 | 三种来源均生成 item.json 骨架 |
| **M2 图片分析** | `stylevault-analyze-image`；本地特征 + LLM 语义入库 | 2 天 | 10 张图全部产出六类标签 |
| **M3 视频分析** | ffmpeg 抽帧/场景切分/节奏统计；复用 M2 帧分析 | 2 天 | 3 个视频产出含节奏的完整分析 |
| **M4 检索+UI** | `stylevault-search` + PWA 画廊（复用 pdf-reader 经验） | 2 天 | 标签筛选/关键词/相似案例可用 |
| **M5 知识问答** | 对库提问："低角度逆光有什么参考" | 1 天 | 能基于库内容回答并给案例 |
| **M6 剪辑辅助** | 剪辑引擎读 style_tags/editing 做镜头/节奏推荐（不在 V1） | 未来 | — |

**V1 完成 = M1–M5 全部可用。**

### 风险与对策

| 风险 | 对策 |
|---|---|
| iSH 网络慢 / apk 安装久 | 后台安装+进度说明；分析全部本地优先，不依赖网络 |
| LLM 输出不稳定 | 严格 JSON schema + 重试 + 低置信度标记 needs_review |
| 视频文件大、分析慢 | 只存关键帧+元数据；原片可选保留或外链 |
| musl 兼容问题 | 只用 apk 包，不 pip 装 C 扩展（复用 pdf-reader 踩坑经验） |
| 标签体系漂移 | 版本化标签本体；tags.json 可重建；旧条目重放不报废 |

---

*文档结束 · StyleVault Architecture v0.1*
