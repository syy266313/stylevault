#!/usr/bin/env python3
"""Read-only M4.0 regression checks for durable query properties."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from search import search  # noqa: E402


def snapshot(root):
    paths = []
    for base in (Path(root) / "items", Path(root) / "indexes"):
        if base.exists():
            paths.extend(path for path in base.rglob("*") if path.is_file())
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def source_metadata(root):
    metadata = {}
    for path in (Path(root) / "items").glob("*/item.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(item, dict) and item.get("id"):
            metadata[item["id"]] = item
    return metadata


def check_filters(result, args, metadata):
    checks = []
    for row in result["results"]:
        item = metadata.get(row["item_id"], {})
        if args.get("item_type"):
            checks.append(item.get("type") == args["item_type"])
        if args.get("collection"):
            checks.append(args["collection"] in item.get("collections", []))
        if args.get("preference_min") is not None:
            preference = (item.get("analysis") or {}).get("preference")
            threshold = args["preference_min"] * 5 if args["preference_min"] <= 1 else args["preference_min"]
            checks.append(isinstance(preference, (int, float)) and preference >= threshold)
    return all(checks) if checks else True


def evaluate(root, config):
    metadata = source_metadata(root)
    before = snapshot(root)
    reports = []
    all_ok = True
    for query in config["queries"]:
        args = query["args"]
        first = search(root, tags=args.get("tags"), mode=args.get("mode", "and"), item_type=args.get("item_type"), collection=args.get("collection"), preference_min=args.get("preference_min"), text=args.get("text"))
        second = search(root, tags=args.get("tags"), mode=args.get("mode", "and"), item_type=args.get("item_type"), collection=args.get("collection"), preference_min=args.get("preference_min"), text=args.get("text"))
        rows = first["results"]
        ids = [row["item_id"] for row in rows]
        scores = [row["score"] for row in rows]
        unique = len(ids) == len(set(ids))
        sorted_scores = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
        ties = all(scores[i] != scores[i + 1] or ids[i] <= ids[i + 1] for i in range(len(ids) - 1))
        stable = first == second
        expected = query.get("expect", {})
        expected_shape = (not expected.get("non_empty") or bool(rows)) and (not expected.get("empty") or not rows)
        filters_ok = check_filters(first, args, metadata)
        ok = unique and sorted_scores and ties and stable and expected_shape and filters_ok
        reports.append({"id": query["id"], "ok": ok, "count": len(rows), "stable": stable, "unique": unique, "sorted_scores": sorted_scores, "stable_item_id_tie_break": ties, "filters_respected": filters_ok})
        all_ok = all_ok and ok
    after = snapshot(root)
    unchanged = before == after
    return {"ok": all_ok and unchanged, "queries": reports, "source_files_unchanged": unchanged}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run M4.0 deterministic query regression")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[3] / "configs" / "search-m4.0-regression.json"))
    parser.add_argument("--vault-root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        report = evaluate(Path(args.vault_root), config)
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0 if report["ok"] else 1
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
