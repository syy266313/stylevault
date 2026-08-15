#!/usr/bin/env python3
"""StyleVault ingest — 采集与落盘（M1）

采集与分析解耦：本脚本只负责 导入→去重→落盘→生成骨架→入队，
不执行任何视觉/语义分析（status=pending，等待 analyze skill 消费）。

三入口：
  1. 附件/本地文件:  python3 ingest.py <file> [--note ...]
  2. apple-photos:   python3 ingest.py --photos [N] [--note ...]
  3. URL/browser:    python3 ingest.py --url <url> [--note ...] [--full-page]

去重：SHA-1。重复素材不建新 item，仅追加 source.refs 引用。

设计原则：文件即数据库；JSON 是事实来源；queue 为派生数据可重建。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

VAULT_ROOT = os.environ.get("STYLEVAULT_ROOT", "/var/minis/shared/stylevault")
ITEMS_DIR = os.path.join(VAULT_ROOT, "items")
QUEUE_FILE = os.path.join(VAULT_ROOT, "indexes", "queue.json")
CONFIG_FILE = os.path.join(VAULT_ROOT, "configs", "pipeline.json")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
ALLOWED_EXTS = IMAGE_EXTS | VIDEO_EXTS
ORIGINS = {"attachment", "photos", "browser", "url", "import"}


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def media_type_of(ext):
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def mime_of(ext):
    e = ext.lstrip(".").lower()
    if e in ("jpg", "jpeg"):
        return "image/jpeg"
    return {"png": "image/png", "gif": "image/gif", "webp": "image/webp", "heic": "image/heic",
            "mp4": "video/mp4", "mov": "video/quicktime", "mkv": "video/x-matroska",
            "webm": "video/webm"}.get(e, "application/octet-stream")


def current_analyze_version():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f).get("current_analyze_version", "v1")
    except Exception:
        return "v1"


def scan_hashes():
    """扫描所有 item.json，返回 {sha1: item_dir}（事实来源全检，跨天也能去重）"""
    found = {}
    if not os.path.isdir(ITEMS_DIR):
        return found
    for name in os.listdir(ITEMS_DIR):
        d = os.path.join(ITEMS_DIR, name)
        if not os.path.isdir(d):
            continue
        p = os.path.join(d, "item.json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p) as f:
                meta = json.load(f)
            h = (meta.get("file") or {}).get("sha1")
            if h:
                found[h] = d
        except Exception:
            continue
    return found


def enqueue(item_id):
    """入分析队列（派生数据，可重建；analyze skill 消费后移除）"""
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    queue = {"version": 1, "entries": []}
    if os.path.isfile(QUEUE_FILE):
        try:
            with open(QUEUE_FILE) as f:
                queue = json.load(f)
        except Exception:
            pass
    if not any(e.get("id") == item_id for e in queue.get("entries", [])):
        queue.setdefault("entries", []).append({"id": item_id, "enqueued_at": now_iso(), "status": "pending"})
        with open(QUEUE_FILE, "w") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
    return queue


def make_skeleton(item_id, media_type, origin, src_path, sha1, note=None, url=None, title=None, album=None):
    """生成 item.json 骨架：只含事实信息，analysis 置 pending"""
    ext = os.path.splitext(src_path)[1].lower()
    stat = os.stat(src_path)
    rel = os.path.join("items", item_id, "source" + ext)
    return {
        "id": item_id,
        "type": media_type,
        "source": {
            "origin": origin,
            "url": url,
            "title": title,
            "album": album,
            "note": note,
        },
        "file": {
            "path": rel,
            "sha1": sha1,
            "mime": mime_of(ext),
            "size": stat.st_size,
            "width": None,
            "height": None,
            "duration_ms": 0,
        },
        "created_at": now_iso(),
        "captured_at": None,
        "collections": [],
        "analyze_version": current_analyze_version(),
        "embedding": {"status": "none", "model": None, "version": None},
        "analysis": {
            "status": "pending",
            "model": None,
            "subject": None, "style": None, "mood": None, "color": None,
            "composition": None, "lighting": None, "camera": None,
            "rhythm": None, "preference": None, "summary": None,
        },
        "vision": None,
        "pipeline_log": [
            {"at": now_iso(), "analyze_version": current_analyze_version(), "action": "ingest",
             "origin": origin, "status": "ok"},
        ],
    }


def import_file(src_path, origin="attachment", note=None, url=None, title=None, album=None):
    """核心落盘逻辑：sha1 → 去重 → 建目录 → 存文件 → 写骨架 → 入队"""
    src_path = os.path.abspath(src_path)
    if not os.path.isfile(src_path):
        return {"ok": False, "error": f"文件不存在: {src_path}"}
    ext = os.path.splitext(src_path)[1].lower()
    mtype = media_type_of(ext)
    if not mtype:
        return {"ok": False, "error": f"不支持的文件类型 {ext}（支持 {sorted(ALLOWED_EXTS)}）"}
    if origin not in ORIGINS:
        return {"ok": False, "error": f"未知来源 {origin}"}

    sha1 = sha1_file(src_path)
    hashes = scan_hashes()

    # --- 去重命中：不建新 item，追加 source.refs ---
    if sha1 in hashes:
        item_dir = hashes[sha1]
        meta_path = os.path.join(item_dir, "item.json")
        with open(meta_path) as f:
            meta = json.load(f)
        refs = meta.setdefault("source", {}).setdefault("refs", [])
        refs.append({
            "origin": origin, "path": src_path, "url": url, "note": note, "at": now_iso(),
        })
        with open(meta_path, "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return {"ok": True, "result": "duplicate", "item_id": meta["id"],
                "item_dir": item_dir, "refs_count": len(refs),
                "message": f"重复素材，已在 {meta['id']} 追加第 {len(refs)} 条来源引用"}

    # --- 新素材：落盘 ---
    item_id = "sv_{}_{}".format(datetime.now().strftime("%Y%m%d"), sha1[:8])
    item_dir = os.path.join(ITEMS_DIR, item_id)
    if not os.path.isdir(item_dir):
        os.makedirs(item_dir)

    dest = os.path.join(item_dir, "source" + ext)
    if not os.path.exists(dest):
        shutil.copy2(src_path, dest)

    meta = make_skeleton(item_id, mtype, origin, dest, sha1, note, url, title, album)
    with open(os.path.join(item_dir, "item.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    queue = enqueue(item_id)
    return {"ok": True, "result": "created", "item_id": item_id, "item_dir": item_dir,
            "path": dest, "queue_size": len(queue.get("entries", [])),
            "message": f"已入库 {item_id}，分析已入队(status=pending)"}


def run(cmd):
    """执行外部 CLI（apple-photos / minis-browser-use），返回解析后的 data 字典"""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "命令超时: " + " ".join(cmd)}
    try:
        d = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"非 JSON 输出: {out.stdout[:200]}"}
    if not isinstance(d, dict):
        return {"ok": False, "error": f"非对象 JSON: {str(d)[:200]}"}
    if "ok" not in d:
        # -q/--quiet 模式：输出为裸 data（无 ok/data 包装键）→ 视为成功
        return {"ok": True, "data": d.get("data", d)}
    if not d.get("ok"):
        return {"ok": False, "error": d.get("error") or d.get("reason") or str(d)}
    return {"ok": True, "data": d.get("data", {})}


def ingest_photos(n=None, note=None):
    """apple-photos 入口：list → export --id → import"""
    r = run(["apple-photos", "list", "--limit", "20", "--compact", "-q"])
    if not r["ok"]:
        return r
    assets = r["data"] if isinstance(r["data"], list) else r["data"].get("assets", [])
    if not assets:
        return {"ok": False, "error": "相册为空"}
    if n is None:
        print("最近素材（--photos N 指定序号导入）：")
        for i, a in enumerate(assets, 1):
            print(f"  [{i}] {a.get('date','')} {a.get('type','')} {a.get('width','')}x{a.get('height','')} {a.get('id','')}")
        print("未指定 N，默认导入第 1 条")
        n = 1
    if not (1 <= n <= len(assets)):
        return {"ok": False, "error": f"--photos {n} 超出范围（1-{len(assets)}）"}
    asset = assets[n - 1]
    r = run(["apple-photos", "export", "--id", asset["id"]])
    if not r["ok"]:
        return r
    exp = r["data"]
    return import_file(exp["path"], origin="photos", note=note, album=asset.get("album"),
                       title=asset.get("date", ""), url=None)


def ingest_url(url, note=None, full_page=False):
    """URL 入口：browser_use 导航 → 截图 → 以截图落盘，source 记录 url/title"""
    r = run(["minis-browser-use", "navigate", "--url", url])
    if not r["ok"]:
        return r
    info = run(["minis-browser-use", "get_page_info"])
    title = None
    if info["ok"]:
        title = info["data"].get("title")
        if not title:
            m = re.search(r"title:\s*(.+)", info["data"].get("text", ""))
            title = m.group(1).strip() if m else None
    if not title:
        m = re.search(r"Title:\s*(.+)", r["data"].get("text", ""))
        title = m.group(1).strip() if m else url
    sc = ["minis-browser-use", "screenshot"]
    if full_page:
        sc.append("--full-page")
    r = run(sc)
    if not r["ok"]:
        return r
    shot = r["data"].get("image_path")
    if not shot:
        return {"ok": False, "error": "截图未返回路径"}
    return import_file(shot, origin="browser", note=note, url=url, title=title)


def show_queue():
    if not os.path.isfile(QUEUE_FILE):
        print("队列为空")
        return
    with open(QUEUE_FILE) as f:
        q = json.load(f)
    print(json.dumps(q, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="StyleVault ingest (M1)")
    ap.add_argument("file", nargs="?", help="本地文件/附件路径")
    ap.add_argument("--photos", nargs="?", type=int, const=1, metavar="N",
                    help="从 apple-photos 导入（默认第 1 条，可指定序号）")
    ap.add_argument("--list-photos", action="store_true", help="列出相册最近 20 条素材")
    ap.add_argument("--url", metavar="URL", help="URL 采集（browser_use 截图）")
    ap.add_argument("--note", help="用户备注")
    ap.add_argument("--full-page", action="store_true", help="URL 采集时整页截图")
    ap.add_argument("--origin", default="attachment", choices=sorted(ORIGINS),
                    help="本地文件导入时的来源通道（默认 attachment）")
    ap.add_argument("--queue", action="store_true", help="查看分析队列")
    ap.add_argument("--vault", help="覆盖 vault 根目录（默认 $STYLEVAULT_ROOT 或 shared/stylevault）")
    args = ap.parse_args()

    global VAULT_ROOT, ITEMS_DIR, QUEUE_FILE, CONFIG_FILE
    if args.vault:
        VAULT_ROOT = args.vault
        ITEMS_DIR = os.path.join(VAULT_ROOT, "items")
        QUEUE_FILE = os.path.join(VAULT_ROOT, "indexes", "queue.json")
        CONFIG_FILE = os.path.join(VAULT_ROOT, "configs", "pipeline.json")

    if args.queue:
        show_queue()
        return

    if args.list_photos:
        r = run(["apple-photos", "list", "--limit", "20", "--compact", "-q"])
        if not r["ok"]:
            print(json.dumps(r, ensure_ascii=False, indent=2)); sys.exit(1)
        assets = r["data"] if isinstance(r["data"], list) else r["data"].get("assets", [])
        for i, a in enumerate(assets, 1):
            print(f"[{i}] {a.get('date','')} {a.get('type','')} {a.get('width','')}x{a.get('height','')} {a.get('id','')}")
        return

    if args.photos is not None:
        r = ingest_photos(args.photos, args.note)
    elif args.url:
        r = ingest_url(args.url, args.note, args.full_page)
    elif args.file:
        r = import_file(args.file, origin=args.origin, note=args.note)
    else:
        ap.print_help()
        return

    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)


if __name__ == "__main__":
    main()
