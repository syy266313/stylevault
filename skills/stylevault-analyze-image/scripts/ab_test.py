#!/usr/bin/env python3
"""StyleVault M2.5 A/B 视觉分析评测

对 Golden Dataset（configs/golden-dataset.json）中的图片分别用两个多模态模型
做 Phase B 语义分析，对比：准确率（vs golden）、标签稳定性、JSON 一致性、
平均延迟、token 成本。

用法:
  python3 ab_test.py --model-a H/gpt-5.6-luna-high --model-b H/gpt-5.6-luna-xhigh
  python3 ab_test.py --model-a ... --model-b ... --sample 5 --repeat 2   # 子集+稳定性重跑
  python3 ab_test.py --report-only                                      # 只看已有结果

输出: configs/ab_results/<model>_<ts>.jsonl + 终端报告
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
from datetime import datetime

VAULT = "/var/minis/shared/stylevault"
GOLDEN_FILE = os.path.join(VAULT, "configs", "golden-dataset.json")
RESULT_DIR = os.path.join(VAULT, "configs", "ab_results")
DIMS = ["subject", "style", "mood", "color", "composition", "lighting", "camera"]
TAG_RE = re.compile(r"^[a-z-]+:[a-z0-9-]+$")

ANALYSIS_PROMPT = """你是资深视觉分析师。查看图片，输出严格 JSON（不要多余文字）：
{
  "subject": {"tags": ["subject:xxx"], "summary": "一句话", "confidence": 0.0-1.0},
  "style": {...}, "mood": {...}, "color": {...}, "composition": {...},
  "lighting": {...}, "camera": {...}, "rhythm": null,
  "preference": 1-5,
  "editing_rules": [{"aspect": "color", "rule": "含具体参数的可执行调色/剪辑/出图指令，如 hue-8 sat+5、+25%、50mm f/1.8"}],
  "summary": "一句话总评"
}
规则: 标签格式 维度:值（如 composition:rule-of-thirds）；rhythm 对图片必须 null；
editing_rules 1-4 条，rule 必须含可执行参数；不要编造图中不存在的细节。"""


def log(msg):
    print(msg, flush=True)


def img_to_data_url(path):
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        ext = os.path.splitext(path)[1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "heic": "image/heic", "webp": "image/webp"}.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def call_model(model_id, image_path, timeout=300):
    """调 minis-model-use 做视觉分析，返回 (ok, data, latency, usage)"""
    body = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": ANALYSIS_PROMPT},
                {"type": "image_url", "image_url": {"url": img_to_data_url(image_path)}},
            ],
        }]
    }
    inp = "/tmp/sv_ab_input.json"
    with open(inp, "w") as f:
        json.dump(body, f)
    t0 = time.time()
    try:
        out = subprocess.run(["minis-model-use", "run", "--model", model_id,
                              "--input", inp, "--max-tokens", "3000"],
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, {"error": "timeout"}, time.time() - t0, {}
    latency = time.time() - t0
    try:
        d = json.loads(out.stdout)
    except json.JSONDecodeError:
        return False, {"error": f"非 JSON 输出: {out.stdout[:200]}"}, latency, {}
    if not d.get("ok"):
        return False, {"error": d.get("error", {}).get("message", str(d)[:200])}, latency, {}
    data = d.get("data", d)
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    return True, data, latency, usage


def extract_json(text):
    """从模型输出提取 JSON（容忍 ```json 包裹/前后杂文本）"""
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


def parse_response(data):
    """从 minis-model-use 响应 data 中提取 content 文本"""
    if isinstance(data, dict) and "choices" in data:
        return data["choices"][0].get("message", {}).get("content", "")
    if isinstance(data, dict) and "content" in data:
        return data["content"]
    return json.dumps(data, ensure_ascii=False)


def validate_analysis(a):
    """结构校验，返回 (ok, errors)"""
    errs = []
    if not isinstance(a, dict):
        return False, ["非对象"]
    for dim in DIMS:
        v = a.get(dim)
        if not isinstance(v, dict) or not v.get("tags"):
            errs.append(f"{dim} 缺失/无标签")
    for dim in DIMS:
        v = a.get(dim) or {}
        for t in v.get("tags") or []:
            if not TAG_RE.match(t):
                errs.append(f"{dim} 标签格式: {t}")
    if a.get("rhythm") is not None:
        errs.append("rhythm 应为 null")
    if not isinstance(a.get("preference"), int) or not (1 <= a["preference"] <= 5):
        errs.append("preference 非法")
    if not isinstance(a.get("editing_rules"), list) or not a["editing_rules"]:
        errs.append("editing_rules 缺失")
    return not errs, errs


def score_vs_golden(a, golden):
    """准确率：每维度 tags ∩ golden / len(golden)，返回 (per_dim, overall)"""
    per_dim = {}
    scored, hit = 0, 0
    for dim in DIMS:
        g = golden.get(dim)
        if not g:
            continue  # golden 无标注不计分
        model_tags = set((a.get(dim) or {}).get("tags") or [])
        gset = set(g)
        s = len(model_tags & gset) / len(gset) if gset else 0.0
        per_dim[dim] = round(s, 3)
        scored += 1
        hit += len(model_tags & gset) / len(gset)
    return per_dim, (round(hit / scored, 3) if scored else None)


def jaccard(a, b):
    """标签稳定性：两个输出的 tag 集合 Jaccard 相似度"""
    ta = {t for dim in DIMS for t in ((a.get(dim) or {}).get("tags") or [])}
    tb = {t for dim in DIMS for t in ((b.get(dim) or {}).get("tags") or [])}
    if not ta and not tb:
        return 1.0
    return round(len(ta & tb) / len(ta | tb), 3)


def load_golden():
    with open(GOLDEN_FILE) as f:
        return json.load(f)["images"]


def item_image_path(item_id):
    p = os.path.join(VAULT, "items", item_id, "source")
    for ext in (".jpg", ".jpeg", ".png", ".heic", ".webp"):
        if os.path.isfile(p + ext):
            return p + ext
    return None


def run_ab(model_a, model_b, sample=None, repeat=1):
    images = load_golden()
    if sample:
        images = images[:sample]
    log(f"评测集: {len(images)} 张 × 模型[{model_a} vs {model_b}] repeat={repeat}")
    os.makedirs(RESULT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []

    for img in images:
        item_id, name = img["item_id"], img["name"]
        path = item_image_path(item_id)
        if not path:
            log(f"  ✗ {name}: 源文件缺失"); continue
        row = {"item_id": item_id, "name": name, "golden": img["golden"],
               "runs": {"a": [], "b": []}}
        for key, model in (("a", model_a), ("b", model_b)):
            for r in range(repeat):
                ok, data, latency, usage = call_model(model, path)
                if not ok:
                    row["runs"][key].append({"ok": False, "error": data.get("error", "?")})
                    log(f"  ✗ {name} [{key}] 调用失败: {data.get('error','')[:80]}")
                    continue
                content = parse_response(data)
                analysis = extract_json(content)
                valid, errs = validate_analysis(analysis) if analysis else (False, ["JSON 解析失败"])
                rec = {"ok": True, "latency": round(latency, 2), "usage": usage,
                       "valid": valid, "errors": errs[:3], "analysis": analysis}
                row["runs"][key].append(rec)
                log(f"  ✓ {name} [{key}] r{r+1}: {'valid' if valid else 'INVALID:'+str(errs[:2])} {latency:.1f}s")
        results.append(row)

    out = os.path.join(RESULT_DIR, f"ab_{ts}.json")
    with open(out, "w") as f:
        json.dump({"ts": ts, "model_a": model_a, "model_b": model_b, "results": results},
                  f, ensure_ascii=False, indent=2)
    log(f"\n结果已存: {out}")
    report(results, model_a, model_b)


def report(results, model_a, model_b):
    log("\n" + "=" * 68)
    log("M2.5 A/B 评测报告")
    log("=" * 68)
    for key, label in (("a", model_a), ("b", model_b)):
        ok = [r for r in results if r["runs"][key]]
        n = len(ok)
        if not n:
            log(f"\n[{label}] 无有效结果"); continue
        lat = [run["latency"] for r in ok for run in r["runs"][key] if run.get("ok")]
        valid = [run for r in ok for run in r["runs"][key] if run.get("ok")]
        v_ok = [v for v in valid if v.get("valid")]
        tok_in = sum((u.get("prompt_tokens") or 0) for r in ok for u in [run.get("usage") or {} for run in r["runs"][key]])
        tok_out = sum((u.get("completion_tokens") or 0) for r in ok for u in [run.get("usage") or {} for run in r["runs"][key]])
        log(f"\n■ {label}")
        log(f"  JSON 一致性 : {len(v_ok)}/{len(valid)} 解析+结构校验通过 ({round(len(v_ok)/len(valid)*100,1)}%)" if valid else "  无调用")
        if v_ok:
            accs, per = [], {}
            for r in ok:
                for run in r["runs"][key]:
                    if not run.get("valid"):
                        continue
                    pd, ov = score_vs_golden(run["analysis"], r["golden"])
                    if ov is not None:
                        accs.append(ov)
                        for dim, s in pd.items():
                            per.setdefault(dim, []).append(s)
            if accs:
                log(f"  准确率(overall, vs golden): {round(sum(accs)/len(accs)*100,1)}%  ({len(accs)} 次评分)")
                log("  维度准确率: " + " | ".join(f"{d}={round(sum(v)/len(v)*100,1)}%" for d, v in per.items()))
            if len(results) >= 2 and key == "a":
                stab = [jaccard(r["runs"]["a"][0]["analysis"], r["runs"]["b"][0]["analysis"])
                        for r in results if r["runs"]["a"] and r["runs"]["b"] and r["runs"]["a"][0].get("valid") and r["runs"]["b"][0].get("valid")]
                if stab:
                    log(f"  标签稳定性(A/B 跨模型 Jaccard): {round(sum(stab)/len(stab)*100,1)}%")
        if lat:
            log(f"  平均延迟 : {round(sum(lat)/len(lat),2)}s ({len(lat)} 次)")
        if tok_in or tok_out:
            log(f"  token    : in={tok_in} out={tok_out} 合计={tok_in+tok_out}")


def main():
    ap = argparse.ArgumentParser(description="StyleVault M2.5 A/B 视觉分析评测")
    ap.add_argument("--model-a", default="H/gpt-5.6-luna-high")
    ap.add_argument("--model-b", default="H/gpt-5.6-luna-xhigh")
    ap.add_argument("--sample", type=int, help="只测前 N 张")
    ap.add_argument("--repeat", type=int, default=1, help="同模型重复次数（稳定性）")
    args = ap.parse_args()
    run_ab(args.model_a, args.model_b, args.sample, args.repeat)


if __name__ == "__main__":
    main()
