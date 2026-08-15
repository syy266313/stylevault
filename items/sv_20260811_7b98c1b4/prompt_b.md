# StyleVault 视觉语义分析任务

你是资深视觉分析师。请查看图片，结合本地特征快照，输出**严格 JSON**。

## 图片
路径: `/var/minis/shared/stylevault/items/sv_20260811_7b98c1b4/source.jpg`
（agent：用 read_image 查看图片内容）

## 本地特征快照（仅供参考，以你的视觉判断为准）
```json
{
  "classifications": [
    {
      "label": "document",
      "confidence": 0.5590820908546448
    },
    {
      "label": "screenshot",
      "confidence": 0.55908203125
    },
    {
      "label": "printed_page",
      "confidence": 0.45361328125
    }
  ],
  "faces": {
    "count": 0
  },
  "ocr": {
    "block_count": 6,
    "text": "Example Domain\nThis domain is for use in\ndocumentation examples\nwithout needing permission.\nAvoid use in operations.\nLearn more"
  },
  "palette": [
    {
      "hex": "#eeeeee",
      "ratio": 0.923
    },
    {
      "hex": "#cccccc",
      "ratio": 0.025
    },
    {
      "hex": "#dddddd",
      "ratio": 0.021
    },
    {
      "hex": "#ffffff",
      "ratio": 0.017
    },
    {
      "hex": "#aaaaaa",
      "ratio": 0.005
    }
  ],
  "brightness": 0.924,
  "saturation": 0.0,
  "width": 1170,
  "height": 2532,
  "source": "apple-vision + pillow"
}
```

## 条目背景
- id: sv_20260811_7b98c1b4
- type: image
- 来源: browser https://example.com
- 用户备注: 网页案例测试

## 标签本体（八维）
- subject: 可选值 portrait, landscape, product, architecture, food, fashion, abstract, street, nature, vehicle, technology, character…（可新增，格式 subject:值）
- style: 可选值 cinematic, minimal, cyberpunk, film, documentary, neo-chinese, retro, vintage, surreal, flat-design, glitch, lo-fi（可新增，格式 style:值）
- mood: 可选值 calm, warm, tense, nostalgic, energetic, dreamy, melancholic, joyful, mysterious, epic, intimate, lonely（可新增，格式 mood:值）
- color: 可选值 warm, cool, high-sat, low-sat, desaturated, mono, teal-orange, pastel, high-contrast, natural, neon, earth-tone（可新增，格式 color:值）
- composition: 可选值 rule-of-thirds, symmetry, frame-in-frame, leading-line, negative-space, center, diagonal, golden-ratio, layered, minimal-frame（可新增，格式 composition:值）
- lighting: 可选值 hard, soft, rim, backlight, low-key, high-key, golden-hour, blue-hour, silhouette, window-light, neon-glow, shadow-play（可新增，格式 lighting:值）
- camera: 可选值 close-up, extreme-close-up, medium, wide, extreme-wide, low-angle, high-angle, eye-level, tracking, handheld, dolly, aerial…（可新增，格式 camera:值）
- rhythm: 可选值 fast-cut, long-take, match-cut, j-cut, l-cut, montage, slow-motion, time-lapse, steady, sync-beat, cross-cut, hard-cut（可新增，格式 rhythm:值）

## 输出要求
输出到文件 `/var/minis/shared/stylevault/items/sv_20260811_7b98c1b4/analysis.json`，内容为单个 JSON 对象：

```json
{
  "subject": {"tags": ["subject:xxx"], "summary": "一句话", "confidence": 0.9},
  "style": {...}, "mood": {...}, "color": {...},
  "composition": {...}, "lighting": {...}, "camera": {...},
  "rhythm": null,
  "preference": 4,
  "summary": "一句话总评"
}
```

规则：
1. 每个维度 tags 至少 1 个，格式 `维度:值`；优先使用本体中的值，可新增但须贴切。
2. confidence 0-1；整体判断不自信的维度给低值（<0.6）。
3. 图片条目的 rhythm 必须为 null。
4. preference 1-5：按个人审美价值初评（好案例给高分）。
5. summary 用中文，简洁专业；不要编造图片中不存在的细节（如无人物不要说人像）。
6. 只输出 JSON，不要额外文字。
