#!/usr/bin/env python3
"""StyleVault analyze-image — 图片两级分析（M2）

Phase A（本地确定性特征，脚本化）：
  apple-vision analyze（classify/faces/ocr）+ pillow（主色调/亮度/饱和度）
  → 写 item.json 的 vision 字段（幂等，可重跑）

Phase B（语义分析，agent 执行）：
  prompt <id> 生成提示词文件（含 vision 快照 + 标签本体 + 输出要求）
  → agent 用 read_image 看图并按提示输出 JSON 到 <item_dir>/analysis.json
  → apply <id> 校验并写回 analysis 字段（status=done），队列移除

设计原则：文件即数据库；JSON 是事实来源；低置信度标 needs_review；全流程幂等。
"""
import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from collections import Counter
from datetime import datetime, timezone

try:
    from PIL import Image
except ImportError:
    Image = None

VAULT_ROOT = os.environ.get("STYLEVAULT_ROOT", "/var/minis/shared/stylevault")
ITEMS_DIR = os.path.join(VAULT_ROOT, "items")
QUEUE_FILE = os.path.join(VAULT_ROOT, "indexes", "queue.json")
ONTOLOGY_FILE = os.path.join(VAULT_ROOT, "configs", "tag-ontology.json")
CONFIG_FILE = os.path.join(VAULT_ROOT, "configs", "pipeline.json")
SCHEMA_FILE = os.path.join(VAULT_ROOT, "schemas", "item.schema.json")
DIMENSIONS = ["subject", "style", "mood", "color", "composition", "lighting", "camera", "rhythm"]
TAG_RE = re.compile(r"^[a-z-]+:[a-z0-9-]+$")


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log(msg):
    print(msg, flush=True)


def item_paths():
    """返回 {item_id: 目录绝对路径}"""
    out = {}
    if not os.path.isdir(ITEMS_DIR):
        return out
    for name in sorted(os.listdir(ITEMS_DIR)):
        d = os.path.join(ITEMS_DIR, name)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "item.json")):
            out[name] = d
    return out


def load_item(item_id):
    d = item_paths().get(item_id)
    if not d:
        return None, None
    with open(os.path.join(d, "item.json")) as f:
        return json.load(f), d


def save_item(item_id, meta, d):
    with open(os.path.join(d, "item.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def load_ontology():
    try:
        with open(ONTOLOGY_FILE) as f:
            return json.load(f)
    except Exception:
        return {"dimensions": {}}


def load_pipeline():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {"current_analyze_version": "v1"}


def queue_entries():
    try:
        with open(QUEUE_FILE) as f:
            return json.load(f).get("entries", [])
    except Exception:
        return []


def dequeue(item_id):
    q = {"version": 1, "entries": []}
    if os.path.isfile(QUEUE_FILE):
        try:
            with open(QUEUE_FILE) as f:
                q = json.load(f)
        except Exception:
            pass
    q["entries"] = [e for e in q.get("entries", []) if e.get("id") != item_id]
    with open(QUEUE_FILE, "w") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)
    return len(q["entries"])


def run_vision(image_path):
    """apple-vision analyze → 结构化数据"""
    try:
        out = subprocess.run(["apple-vision", "analyze", image_path, "--compact"],
                             capture_output=True, text=True, timeout=120)
        d = json.loads(out.stdout)
    except Exception as e:
        return {"error": str(e)}
    data = d.get("data", d) if isinstance(d, dict) else d
    return data


def pillow_features(image_path):
    """pillow：主色调 Top5 / 亮度 / 饱和度 / 尺寸（失败降级，不阻塞 Phase A）"""
    try:
        if Image is None:
            return {"error": "pillow 未安装 (apk add py3-pillow)"}
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        small = img.resize((64, 64))
        px = list(small.getdata())
        total = len(px)

        buckets = Counter((r >> 4, g >> 4, b >> 4) for r, g, b in px)
        palette = []
        for (r, g, b), c in buckets.most_common(5):
            palette.append({"hex": "#{:02x}{:02x}{:02x}".format((r << 4) | r, (g << 4) | g, (b << 4) | b),
                            "ratio": round(c / total, 3)})

        gray = small.convert("L")
        brightness = round(sum(gray.getdata()) / (total * 255), 3)
        hsv = small.convert("HSV")
        saturation = round(sum(p[1] for p in hsv.getdata()) / (total * 255), 3)
        return {"width": w, "height": h, "palette": palette, "brightness": brightness,
                "saturation": saturation, "source": "pillow-11"}
    except Exception as e:
        return {"error": f"pillow 读取失败: {e}"}


def phase_a(item_id, force=False):
    """Phase A：本地确定性特征 → vision 字段（幂等）"""
    meta, d = load_item(item_id)
    if not meta:
        dequeue(item_id)  # 清理失效队列项
        return {"ok": False, "error": f"条目不存在: {item_id}（已从队列移除）"}
    if meta.get("analysis", {}).get("status") == "done" and meta.get("vision") and not force:
        return {"ok": True, "result": "skipped", "item_id": item_id, "message": "已有 vision，跳过（--force 重跑）"}

    src = os.path.join(d, os.path.basename(meta["file"]["path"]))
    if not os.path.isfile(src):
        return {"ok": False, "error": f"源文件缺失: {src}"}

    vision = run_vision(src)
    if "error" in vision:
        return {"ok": False, "error": f"apple-vision 失败: {vision['error']}"}

    feat = pillow_features(src)
    if "error" in feat:
        log(f"  ⚠ pillow 特征失败（跳过）: {feat['error']}")
        feat = {}

    vision_out = {
        "classifications": vision.get("classification", []),
        "faces": vision.get("faces", {}),
        "ocr": vision.get("ocr", {}),
        "palette": feat.get("palette", []),
        "brightness": feat.get("brightness"),
        "saturation": feat.get("saturation"),
        "width": feat.get("width") or (vision.get("image") or {}).get("width"),
        "height": feat.get("height") or (vision.get("image") or {}).get("height"),
        "source": "apple-vision + pillow",
    }
    meta["vision"] = vision_out
    meta.setdefault("pipeline_log", []).append(
        {"at": now_iso(), "analyze_version": load_pipeline()["current_analyze_version"],
         "action": "analyze", "phase": "a", "status": "ok"})
    save_item(item_id, meta, d)
    return {"ok": True, "result": "ok", "item_id": item_id,
            "classifications": len(vision_out["classifications"]),
            "palette": len(vision_out["palette"]),
            "brightness": vision_out["brightness"], "saturation": vision_out["saturation"]}


def gen_prompt(item_id):
    """Phase B 提示词生成 → <item_dir>/prompt_b.md"""
    meta, d = load_item(item_id)
    if not meta:
        return {"ok": False, "error": f"条目不存在: {item_id}"}
    if not meta.get("vision"):
        return {"ok": False, "error": "先运行 phase-a 生成 vision 特征"}
    ontology = load_ontology()
    src_abs = os.path.join(d, os.path.basename(meta["file"]["path"]))

    dims_block = "\n".join(
        f"- {dim}: 可选值 {', '.join(v['values'][:12])}{'…' if len(v['values'])>12 else ''}（可新增，格式 {dim}:值）"
        for dim, v in ontology.get("dimensions", {}).items())

    prompt = f"""# StyleVault 视觉语义分析任务

你是资深视觉分析师。请查看图片，结合本地特征快照，输出**严格 JSON**。

## 图片
路径: `{src_abs}`
（agent：用 read_image 查看图片内容）

## 本地特征快照（仅供参考，以你的视觉判断为准）
```json
{json.dumps(meta.get('vision', {}), ensure_ascii=False, indent=2)}
```

## 条目背景
- id: {item_id}
- type: {meta['type']}
- 来源: {meta['source'].get('origin')} {meta['source'].get('title') or ''}
- 用户备注: {meta['source'].get('note') or '（无）'}

## 标签本体（八维）
{dims_block}

## 输出要求
输出到文件 `{os.path.join(d, 'analysis.json')}`，内容为单个 JSON 对象：

```json
{{
  "subject": {{"tags": ["subject:xxx"], "summary": "一句话", "confidence": 0.9}},
  "style": {{...}}, "mood": {{...}}, "color": {{...}},
  "composition": {{...}}, "lighting": {{...}}, "camera": {{...}},
  "rhythm": null,
  "preference": 4,
  "editing_rules": [{{"aspect": "color", "rule": "阴影向青色偏移 hue-8 sat+5，高光偏橙 hue+6，饱和度 105%"}}],
  "summary": "一句话总评"
}}
```

规则：
1. 每个维度 tags 至少 1 个，格式 `维度:值`；优先使用本体中的值，可新增但须贴切。
2. confidence 0-1；整体判断不自信的维度给低值（<0.6）。
3. 图片条目的 rhythm 必须为 null。
4. preference 1-5：按个人审美价值初评（好案例给高分）。
5. **editing_rules（必须）**：1-4 条可直接执行的规则，面向 AI 调色/剪辑/出图。每条 {{"aspect": ..., "rule": ...}}：
   - aspect ∈ color/lighting/composition/camera/rhythm/mood/style/subject
   - rule 必须含具体可执行参数（色值偏移 hue/sat/亮度、曝光 EV、百分比、焦段光圈如 50mm f/1.8、时长如 1.2s、裁剪位置等），禁止空泛描述（如"增强氛围感"不合格，"暗角 +15%、主体亮度 +10%"合格）
   - 规则应忠实复现本图的视觉特征（调色方向、光比、构图比例、镜头参数、节奏数值）
6. summary 用中文，简洁专业；不要编造图片中不存在的细节（如无人物不要说人像）。
7. 只输出 JSON，不要额外文字。
"""
    p = os.path.join(d, "prompt_b.md")
    with open(p, "w") as f:
        f.write(prompt)
    return {"ok": True, "item_id": item_id, "prompt": p, "output_target": os.path.join(d, "analysis.json")}


def validate_analysis(meta, analysis):
    """校验 agent 输出的 analysis JSON，返回 (errors, 清洗后数据)"""
    errors = []
    if not isinstance(analysis, dict):
        return ["输出不是 JSON 对象"], None
    mtype = meta["type"]
    dims = DIMENSIONS if mtype == "video" else [d for d in DIMENSIONS if d != "rhythm"]
    for dim in dims:
        v = analysis.get(dim)
        if v is None:
            errors.append(f"缺少维度 {dim}")
            continue
        if not isinstance(v, dict):
            errors.append(f"{dim} 应为对象")
            continue
        tags = v.get("tags") or []
        if not isinstance(tags, list) or not tags:
            errors.append(f"{dim}.tags 至少 1 个")
        for t in tags:
            if not TAG_RE.match(t):
                errors.append(f"{dim} 标签格式错误: {t}（应为 维度:值）")
        c = v.get("confidence")
        if not isinstance(c, (int, float)) or not (0 <= c <= 1):
            errors.append(f"{dim}.confidence 应为 0-1")
        if not isinstance(v.get("summary"), str) or not v["summary"].strip():
            errors.append(f"{dim}.summary 不能为空")
    if mtype == "image" and analysis.get("rhythm") is not None:
        errors.append("图片条目的 rhythm 必须为 null")
    pref = analysis.get("preference")
    if not isinstance(pref, int) or not (1 <= pref <= 5):
        errors.append("preference 应为 1-5 整数")
    if not isinstance(analysis.get("summary"), str) or not analysis["summary"].strip():
        errors.append("summary 不能为空")
    # editing_rules（M2.5）：非空数组，aspect 合法，rule 含参数
    er = analysis.get("editing_rules")
    if not isinstance(er, list) or not er:
        errors.append("editing_rules 应为非空数组（至少 1 条可执行规则）")
    else:
        for i, e in enumerate(er):
            if not isinstance(e, dict) or e.get("aspect") not in ("color", "lighting", "composition", "camera", "rhythm", "mood", "style", "subject"):
                errors.append(f"editing_rules[{i}] aspect 非法（color/lighting/composition/camera/rhythm/mood/style/subject）")
            if not isinstance(e.get("rule"), str) or len(e["rule"].strip()) < 8:
                errors.append(f"editing_rules[{i}] rule 过短，需含具体参数（如 hue-8 sat+5、+25%、50mm f/1.8）")
    return errors, analysis


def apply_analysis(item_id, json_path=None, analysis=None, force=False):
    """校验并写回 analysis 字段；低置信度标 needs_review；队列移除"""
    meta, d = load_item(item_id)
    if not meta:
        return {"ok": False, "error": f"条目不存在: {item_id}"}
    if meta.get("analysis", {}).get("status") == "done" and not force:
        return {"ok": True, "result": "skipped", "item_id": item_id, "message": "已有分析，跳过（--force 覆盖）"}
    if analysis is None:
        if json_path is None:
            json_path = os.path.join(d, "analysis.json")
        with open(json_path) as f:
            analysis = json.load(f)

    errors, cleaned = validate_analysis(meta, analysis)
    if errors:
        meta.setdefault("analysis", {})["status"] = "error"
        meta["analysis"]["errors"] = errors
        meta.setdefault("pipeline_log", []).append(
            {"at": now_iso(), "action": "analyze", "phase": "b", "status": "error", "errors": errors})
        save_item(item_id, meta, d)
        return {"ok": False, "error": "校验失败", "errors": errors}

    low_conf = [dim for dim in cleaned
                if isinstance(cleaned[dim], dict) and isinstance(cleaned[dim].get("confidence"), (int, float))
                and cleaned[dim]["confidence"] < 0.6]
    status = "needs_review" if low_conf else "done"
    version = load_pipeline()["current_analyze_version"]
    analysis_block = {
        "status": status,
        "model": {"provider": "minis-agent", "name": "stylevault-analyze-image", "version": version},
        "analyzed_at": now_iso(),
    }
    for dim in DIMENSIONS:
        analysis_block[dim] = cleaned.get(dim)
    analysis_block["preference"] = cleaned.get("preference")
    analysis_block["summary"] = cleaned.get("summary")
    analysis_block["editing_rules"] = cleaned.get("editing_rules", [])
    meta["analysis"] = analysis_block
    meta["analyze_version"] = version
    meta.setdefault("pipeline_log", []).append(
        {"at": now_iso(), "analyze_version": version, "action": "analyze", "phase": "b", "status": status})
    save_item(item_id, meta, d)
    left = dequeue(item_id)
    return {"ok": True, "result": status, "item_id": item_id,
            "low_confidence": low_conf, "queue_left": left,
            "message": f"分析完成 status={status}，队列剩余 {left}"}


# ============ Phase B 自动模式（M2.5: 视觉模型 API 调用） ============

DEFAULT_MODEL = "gpt-5.6-terra"

def get_api_config(model=None, base_url=None, api_key=None):
    """从环境变量读取 API 配置（可被 CLI 参数覆盖，模型名不写死）。
    环境变量: STYLEVAULT_MODEL / OPENAI_BASE_URL / OPENAI_API_KEY"""
    model = model or os.environ.get("STYLEVAULT_MODEL") or DEFAULT_MODEL
    base_url = base_url or os.environ.get("OPENAI_BASE_URL")
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    return model, base_url, api_key


def normalize_base(base_url):
    b = base_url.rstrip("/")
    # 兼容 {base}/v1/chat/completions 与 {base}/chat/completions 两种形态
    if b.endswith("/v1") or b.endswith("/chat/completions"):
        return b
    return b + "/v1"


def img_to_data_url(path):
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        ext = os.path.splitext(path)[1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "heic": "image/heic", "webp": "image/webp"}.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def extract_json(text):
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def phase_b_prompt(meta, ontology):
    """构造视觉分析提示词（含条目背景 + 特征快照 + 本体 + 输出要求）"""
    src_abs = os.path.join(VAULT_ROOT, meta["file"]["path"])
    dims_block = "\n".join(
        f"- {dim}: 可选值 {', '.join(v['values'][:12])}{'…' if len(v['values'])>12 else ''}（可新增，格式 {dim}:值）"
        for dim, v in ontology.get("dimensions", {}).items())
    return f"""你是资深视觉分析师。查看图片，输出**严格 JSON**（不要额外文字）。

## 图片
路径: `{src_abs}`

## 本地特征快照（仅供参考，以你的视觉判断为准）
```json
{json.dumps(meta.get('vision', {}), ensure_ascii=False)}
```

## 条目背景
- id: {meta['id']} | type: {meta['type']}
- 来源: {meta['source'].get('origin')} {meta['source'].get('title') or ''}
- 用户备注: {meta['source'].get('note') or '（无）'}

## 标签本体（八维）
{dims_block}

## 输出 JSON 结构（必须）
{{
  "subject": {{"tags": ["subject:xxx"], "summary": "一句话", "confidence": 0.9}},
  "style": {{...}}, "mood": {{...}}, "color": {{...}},
  "composition": {{...}}, "lighting": {{...}}, "camera": {{...}},
  "rhythm": null,
  "preference": 4,
  "editing_rules": [{{"aspect": "color", "rule": "..."}}],
  "summary": "一句话总评"
}}

## 规则
1. 每维度 tags 至少 1 个，格式 `维度:值`；优先用本体值，可新增但须贴切。
2. confidence 0-1；不自信的维度给低值（<0.6）。
3. 图片条目 rhythm 必须为 null。
4. preference 1-5：按个人审美价值初评。
5. **editing_rules（必须 1-4 条）**：可直接执行的规则，面向 AI 调色/剪辑/出图。
   aspect ∈ color/lighting/composition/camera/rhythm/mood/style/subject。
   rule 必须含具体可执行参数，例如：曝光 +0.5EV、对比度 +15、高光 -10、阴影 +5、
   饱和度 105%、色温 4500K、焦段 50mm f/1.8、构图裁切至 4:5 右三分线、
   建议镜头时长 1.2s。禁止空泛描述（如"增强氛围感"不合格）。
6. summary 用中文；不要编造图中不存在的细节。"""


def call_vision_api(model, base_url, api_key, image_path, prompt, timeout=300):
    """调用 OpenAI 兼容视觉 API（中转站）。返回 (ok, content, latency, usage, error)"""
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": img_to_data_url(image_path)}},
            ],
        }],
        "max_tokens": 3000,
        "temperature": 0.2,
    }
    url = f"{normalize_base(base_url)}/chat/completions"
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {api_key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        return False, None, time.time() - t0, {}, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, None, time.time() - t0, {}, f"{e}"
    latency = time.time() - t0
    usage = resp.get("usage", {}) or {}
    try:
        content = resp["choices"][0]["message"]["content"]
    except Exception as e:
        return False, None, latency, usage, f"响应结构异常: {e} {str(resp)[:200]}"
    return True, content, latency, usage, None


def phase_b(item_id, model=None, base_url=None, api_key=None, force=False, timeout=300):
    """Phase B 自动视觉分析：API 调用 → 解析 → 校验 → 写回 analysis + editing_rules"""
    meta, d = load_item(item_id)
    if not meta:
        dequeue(item_id)
        return {"ok": False, "error": f"条目不存在: {item_id}（已从队列移除）"}
    if meta.get("analysis", {}).get("status") == "done" and not force:
        return {"ok": True, "result": "skipped", "item_id": item_id, "message": "已有分析，跳过（--force 覆盖）"}

    model, base_url, api_key = get_api_config(model, base_url, api_key)
    if not base_url or not api_key:
        return {"ok": False, "error": "缺少 API 配置：设置 OPENAI_BASE_URL + OPENAI_API_KEY（或 --base-url/--api-key 参数）"}

    src = os.path.join(d, os.path.basename(meta["file"]["path"]))
    if not os.path.isfile(src):
        return {"ok": False, "error": f"源文件缺失: {src}"}

    ontology = load_ontology()
    prompt = phase_b_prompt(meta, ontology)
    ok, content, latency, usage, err = call_vision_api(model, base_url, api_key, src, prompt, timeout)
    if not ok:
        meta.setdefault("analysis", {}).update({"status": "error", "model": {"provider": "openai", "name": model}})
        meta.setdefault("pipeline_log", []).append(
            {"at": now_iso(), "action": "analyze", "phase": "b", "model": model, "status": "error", "error": err})
        save_item(item_id, meta, d)
        return {"ok": False, "error": f"API 调用失败: {err}", "latency": round(latency, 2)}

    analysis = extract_json(content)
    errors, _ = validate_analysis(meta, analysis) if analysis else (["JSON 解析失败"], None)
    if errors:
        meta.setdefault("analysis", {}).update({"status": "error", "model": {"provider": "openai", "name": model},
                                                "errors": errors})
        meta.setdefault("pipeline_log", []).append(
            {"at": now_iso(), "action": "analyze", "phase": "b", "model": model, "status": "error", "errors": errors})
        save_item(item_id, meta, d)
        return {"ok": False, "error": "校验失败", "errors": errors, "raw": content[:300]}

    low_conf = [dim for dim in analysis if isinstance(analysis[dim], dict)
                and isinstance(analysis[dim].get("confidence"), (int, float))
                and analysis[dim]["confidence"] < 0.6]
    status = "needs_review" if low_conf else "done"
    version = load_pipeline()["current_analyze_version"]
    block = {"status": status,
             "model": {"provider": "openai", "name": model, "version": version},
             "analyzed_at": now_iso(),
             "latency_ms": int(latency * 1000),
             "usage": usage}
    for dim in DIMENSIONS:
        block[dim] = analysis.get(dim)
    block["preference"] = analysis.get("preference")
    block["summary"] = analysis.get("summary")
    block["editing_rules"] = analysis.get("editing_rules", [])
    meta["analysis"] = block
    meta["analyze_version"] = version
    meta.setdefault("pipeline_log", []).append(
        {"at": now_iso(), "analyze_version": version, "action": "analyze", "phase": "b",
         "model": model, "status": status, "latency_ms": int(latency * 1000)})
    save_item(item_id, meta, d)
    left = dequeue(item_id)
    tok = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
    return {"ok": True, "result": status, "item_id": item_id, "model": model,
            "latency": round(latency, 2), "tokens": tok, "low_confidence": low_conf,
            "queue_left": left,
            "message": f"分析完成 status={status}（{model} {latency:.1f}s {tok}tok），队列剩余 {left}"}


def rebuild_index():
    """重建 indexes/tags.json 聚合索引（派生数据）"""
    tags = {}
    collections = {}
    n_done = n_pending = 0
    for item_id, d in item_paths().items():
        with open(os.path.join(d, "item.json")) as f:
            meta = json.load(f)
        st = meta.get("analysis", {}).get("status")
        if st in ("done", "needs_review"):
            n_done += 1
            for dim in DIMENSIONS:
                v = meta["analysis"].get(dim)
                if isinstance(v, dict):
                    for t in v.get("tags") or []:
                        tags.setdefault(t, []).append(item_id)
        else:
            n_pending += 1
        for c in meta.get("collections") or []:
            collections.setdefault(c, []).append(item_id)
    index = {
        "version": 1,
        "built_at": now_iso(),
        "item_count": len(item_paths()),
        "analyzed": n_done,
        "pending": n_pending,
        "tags": tags,
        "collections": collections,
    }
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    with open(os.path.join(VAULT_ROOT, "indexes", "tags.json"), "w") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    return {"ok": True, "items": len(item_paths()), "analyzed": n_done, "pending": n_pending,
            "tags": len(tags), "collections": len(collections)}


def show_status(item_id=None):
    if item_id:
        meta, d = load_item(item_id)
        if not meta:
            print(json.dumps({"ok": False, "error": "条目不存在"}, ensure_ascii=False)); return
        print(json.dumps({"ok": True, "id": item_id, "type": meta["type"],
                          "status": meta.get("analysis", {}).get("status"),
                          "has_vision": bool(meta.get("vision"))}, ensure_ascii=False, indent=2))
        return
    rows = []
    for iid, d in item_paths().items():
        with open(os.path.join(d, "item.json")) as f:
            m = json.load(f)
        rows.append((iid, m.get("type"), m.get("source", {}).get("origin"),
                     m.get("analysis", {}).get("status"), bool(m.get("vision"))))
    print(f"{'item_id':<26} {'type':<7} {'origin':<11} {'status':<12} vision")
    for r in rows:
        print(f"{r[0]:<26} {r[1]:<7} {r[2]:<11} {str(r[3]):<12} {'✓' if r[4] else '—'}")


def main():
    ap = argparse.ArgumentParser(description="StyleVault analyze-image (M2)")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("phase-a", help="Phase A 本地特征 → vision")
    p.add_argument("target", nargs="?", default="queue", help="item_id | all | queue(默认)")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("prompt", help="生成 Phase B 提示词")
    p.add_argument("target", help="item_id | all")

    p = sub.add_parser("apply", help="校验并写回 Phase B 分析结果")
    p.add_argument("item_id")
    p.add_argument("json_path", nargs="?", help="analysis.json 路径（默认 <item_dir>/analysis.json）")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("phase-b", help="Phase B 自动视觉分析（调视觉模型 API，M2.5）")
    p.add_argument("target", nargs="?", default="queue", help="item_id | all | queue(默认)")
    p.add_argument("--model", help="模型名（默认 $STYLEVAULT_MODEL 或 gpt-5.6-terra）")
    p.add_argument("--base-url", help="API 地址（默认 $OPENAI_BASE_URL）")
    p.add_argument("--api-key", help="API Key（默认 $OPENAI_API_KEY）")
    p.add_argument("--force", action="store_true")

    sub.add_parser("rebuild-index", help="重建 tags.json 聚合索引")
    sub.add_parser("queue", help="查看分析队列")
    p = sub.add_parser("status", help="查看条目状态")
    p.add_argument("item_id", nargs="?")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help(); return

    if args.cmd == "queue":
        q = queue_entries()
        print(json.dumps({"ok": True, "count": len(q), "entries": q}, ensure_ascii=False, indent=2))
        return

    if args.cmd == "rebuild-index":
        print(json.dumps(rebuild_index(), ensure_ascii=False, indent=2)); return

    if args.cmd == "status":
        show_status(args.item_id); return

    if args.cmd == "phase-a":
        targets = ([args.target] if args.target != "all" else list(item_paths())) if args.target != "queue" else [e["id"] for e in queue_entries()]
        results = []
        for t in targets:
            r = phase_a(t, args.force)
            results.append(r)
            log(f"  {'✓' if r.get('ok') else '✗'} {t}: {r.get('result', r.get('error', ''))} {r.get('message', '')}")
        log(f"phase-a 完成: {sum(1 for r in results if r.get('ok'))}/{len(results)}")

    elif args.cmd == "phase-b":
        targets = ([args.target] if args.target != "all" else list(item_paths())) if args.target != "queue" else [e["id"] for e in queue_entries()]
        results = []
        for t in targets:
            r = phase_b(t, model=args.model, base_url=args.base_url, api_key=args.api_key, force=args.force)
            results.append(r)
            log(f"  {'✓' if r.get('ok') else '✗'} {t}: {r.get('result', r.get('error', ''))} {r.get('message', '')}")
        ok_n = sum(1 for r in results if r.get('ok'))
        log(f"phase-b 完成: {ok_n}/{len(results)}")
        if ok_n:
            log(f"  平均延迟: {round(sum(r.get('latency',0) for r in results if r.get('ok'))/ok_n, 2)}s | "
                f"总 tokens: {sum(r.get('tokens',0) for r in results if r.get('ok'))}")

    elif args.cmd == "prompt":
        targets = [args.target] if args.target != "all" else list(item_paths())
        for t in targets:
            r = gen_prompt(t)
            log(f"  {'✓' if r.get('ok') else '✗'} {t}: {r.get('prompt', r.get('error', ''))}")

    elif args.cmd == "apply":
        r = apply_analysis(args.item_id, args.json_path, force=args.force)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if r.get("ok") else 1)


if __name__ == "__main__":
    main()
