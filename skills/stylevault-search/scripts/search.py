#!/usr/bin/env python3
"""M4.0 deterministic local search; item.json remains the source of truth."""
import argparse
import json
import re
import sys
from pathlib import Path

DIMENSIONS = ("subject", "style", "mood", "color", "composition", "lighting", "camera")
ACTIVE_STATUS = {"done", "needs_review"}


def load_items(vault_root):
    items = []
    root = Path(vault_root) / "items"
    if not root.is_dir():
        return items
    for path in sorted(root.glob("*/item.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not data.get("id"):
            continue
        analysis = data.get("analysis")
        if not isinstance(analysis, dict) or analysis.get("status") not in ACTIVE_STATUS:
            continue
        sidecar_path = path.with_name("analysis.json")
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            sidecar = {}
        if isinstance(sidecar, dict):
            # item.json remains authoritative; sidecar fills only absent fields.
            merged = dict(analysis)
            for key, value in sidecar.items():
                if key not in merged:
                    merged[key] = value
            data = dict(data)
            data["analysis"] = merged
        items.append((data, path))
    return items


def tokens(text):
    if not text:
        return []
    return [part.casefold() for part in re.findall(r"[^\s,，、;；|]+", str(text)) if part]


def tag_values(item):
    analysis = item.get("analysis") or {}
    values = []
    for dimension in DIMENSIONS:
        block = analysis.get(dimension)
        if isinstance(block, dict):
            values.extend(str(value) for value in (block.get("tags") or []) if value)
    return values


def text_fields(item):
    analysis = item.get("analysis") or {}
    summary = str(analysis.get("summary") or "")
    rules = [str(rule.get("rule") or "") for rule in (analysis.get("editing_rules") or []) if isinstance(rule, dict)]
    return summary, rules


def normalize_preference_min(value):
    if value is None:
        return None
    number = float(value)
    if not 0 <= number <= 5:
        raise ValueError("preference-min must be in [0, 1] or [1, 5]")
    return number * 5 if number <= 1 else number


def candidate_ids(vault_root, requested_tags):
    """Use tags index only as an optional candidate accelerator; fallback is all items."""
    index_path = Path(vault_root) / "indexes" / "tags.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        tag_map = index.get("tags") if isinstance(index, dict) else None
        if not isinstance(tag_map, dict):
            return None, "fallback_no_tags_map"
        ids = set()
        for tag in requested_tags:
            values = tag_map.get(tag)
            if not isinstance(values, list):
                return None, "fallback_tag_missing"
            ids.update(value for value in values if isinstance(value, str))
        return ids, "index"
    except (OSError, json.JSONDecodeError):
        return None, "fallback_index_unavailable"


def search(vault_root, tags=None, mode="and", item_type=None, collection=None, preference_min=None, text=None):
    requested_tags = list(dict.fromkeys(tags or []))
    items = load_items(vault_root)
    candidate, index_used = candidate_ids(vault_root, requested_tags) if requested_tags else (None, "not_needed")
    results = []
    query_tokens = tokens(text)
    min_preference = normalize_preference_min(preference_min)
    for item, path in items:
        item_id = item["id"]
        if candidate is not None and item_id not in candidate:
            continue
        item_tags = set(tag_values(item))
        matched_tags = [tag for tag in requested_tags if tag in item_tags]
        if requested_tags and ((mode == "and" and len(matched_tags) != len(requested_tags)) or (mode == "or" and not matched_tags)):
            continue
        if item_type and item.get("type") != item_type:
            continue
        if collection and collection not in (item.get("collections") or []):
            continue
        raw_preference = (item.get("analysis") or {}).get("preference")
        preference = float(raw_preference) if isinstance(raw_preference, (int, float)) else 0.0
        if min_preference is not None and preference < min_preference:
            continue
        summary, rules = text_fields(item)
        searchable = " ".join([summary] + rules).casefold()
        matched_text = [token for token in query_tokens if token in searchable]
        matched_summary = [token for token in query_tokens if token in summary.casefold()]
        matched_rules = [token for token in query_tokens if any(token in rule.casefold() for rule in rules)]
        if query_tokens and not matched_text:
            continue
        tag_ratio = len(matched_tags) / len(requested_tags) if requested_tags else 0.0
        rule_ratio = len(set(matched_rules)) / len(query_tokens) if query_tokens else 0.0
        summary_ratio = len(set(matched_summary)) / len(query_tokens) if query_tokens else 0.0
        score = 5.0 * tag_ratio + 1.5 * rule_ratio + 1.0 * summary_ratio + 0.2 * (preference / 5.0)
        results.append({
            "item_id": item_id,
            "score": round(score, 6),
            "type": item.get("type"),
            "path": str(path.relative_to(vault_root)),
            "preference": raw_preference,
            "analysis_status": (item.get("analysis") or {}).get("status"),
            "matched_tags": matched_tags,
            "matched_summary_tokens": sorted(set(matched_summary)),
            "matched_rule_tokens": sorted(set(matched_rules)),
        })
    results.sort(key=lambda result: (-result["score"], result["item_id"]))
    return {"query": {"tags": requested_tags, "mode": mode, "type": item_type, "collection": collection, "preference_min": preference_min, "text": text}, "count": len(results), "index_used": index_used, "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description="StyleVault M4.0 deterministic local search")
    parser.add_argument("--vault-root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--tags", help="comma-separated exact tags")
    parser.add_argument("--mode", choices=("and", "or"), default="and")
    parser.add_argument("--type")
    parser.add_argument("--collection")
    parser.add_argument("--preference-min", type=float)
    parser.add_argument("--text")
    args = parser.parse_args(argv)
    tags = args.tag + ([value.strip() for value in args.tags.split(",") if value.strip()] if args.tags else [])
    try:
        print(json.dumps(search(args.vault_root, tags, args.mode, args.type, args.collection, args.preference_min, args.text), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
