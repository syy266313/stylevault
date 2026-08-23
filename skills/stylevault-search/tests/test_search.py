#!/usr/bin/env python3
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
from search import search  # noqa: E402


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "items" / "a").mkdir(parents=True)
        (self.root / "items" / "b").mkdir(parents=True)
        (self.root / "items" / "c").mkdir(parents=True)
        (self.root / "items" / "bad").mkdir(parents=True)
        self.items = {
            "a": self.item("sv_a", ["style:cyberpunk", "color:neon"], "暗色夜景", ["保持低饱和冷调"], 5, "image", ["golden-dataset"]),
            "b": self.item("sv_b", ["style:cyberpunk", "color:dark"], "明亮建筑", ["增加硬光对比"], 3, "image", ["other"]),
            "c": self.item("sv_c", ["style:minimal"], "低饱和夜景", ["保持负空间"], 4, "webpage", ["golden-dataset"]),
        }
        for name, item in self.items.items():
            (self.root / "items" / name / "item.json").write_text(json.dumps(item), encoding="utf-8")
        (self.root / "items" / "bad" / "item.json").write_text("{broken", encoding="utf-8")
        (self.root / "indexes").mkdir()
        self.rebuild_index()

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def item(item_id, tags, summary, rules, preference, item_type, collections):
        dims = {dimension: {"tags": []} for dimension in ("subject", "style", "mood", "color", "composition", "lighting", "camera")}
        for tag in tags:
            dimension = tag.split(":", 1)[0]
            dims.setdefault(dimension, {"tags": []})["tags"].append(tag)
        return {"id": item_id, "type": item_type, "collections": collections, "analysis": {"status": "done", **dims, "summary": summary, "editing_rules": [{"aspect": "color", "rule": rule} for rule in rules], "preference": preference}}

    def rebuild_index(self):
        index = {"version": 1, "tags": {}}
        for item in self.items.values():
            for dimension in ("subject", "style", "mood", "color", "composition", "lighting", "camera"):
                for tag in item["analysis"].get(dimension, {}).get("tags", []):
                    index["tags"].setdefault(tag, []).append(item["id"])
        (self.root / "indexes" / "tags.json").write_text(json.dumps(index), encoding="utf-8")

    def test_and_or_and_deduplicated_results(self):
        self.assertEqual([r["item_id"] for r in search(self.root, ["style:cyberpunk", "color:neon"], "and")["results"]], ["sv_a"])
        self.assertEqual({r["item_id"] for r in search(self.root, ["style:cyberpunk", "style:minimal"], "or")["results"]}, {"sv_a", "sv_b", "sv_c"})

    def test_type_collection_and_preference_filters(self):
        self.assertEqual([r["item_id"] for r in search(self.root, item_type="webpage")["results"]], ["sv_c"])
        self.assertEqual([r["item_id"] for r in search(self.root, collection="golden-dataset")["results"]], ["sv_a", "sv_c"])
        self.assertEqual([r["item_id"] for r in search(self.root, preference_min=0.8)["results"]], ["sv_a", "sv_c"])

    def test_summary_and_editing_rule_text(self):
        result = search(self.root, text="低饱和 冷调")
        self.assertEqual(result["results"][0]["item_id"], "sv_a")
        self.assertIn("冷调", result["results"][0]["matched_rule_tokens"])
        self.assertEqual(search(self.root, text="不存在")["count"], 0)

    def test_missing_fields_and_corrupt_json_are_skipped(self):
        missing = copy.deepcopy(self.items["a"])
        missing["id"] = "sv_missing"
        del missing["analysis"]["summary"]
        (self.root / "items" / "missing").mkdir()
        (self.root / "items" / "missing" / "item.json").write_text(json.dumps(missing), encoding="utf-8")
        result = search(self.root, text="不存在")
        self.assertEqual(result["count"], 0)
        self.assertIn("sv_missing", {r["item_id"] for r in search(self.root)["results"]})

    def test_index_missing_falls_back_to_items(self):
        (self.root / "indexes" / "tags.json").unlink()
        result = search(self.root, ["style:cyberpunk"])
        self.assertEqual({r["item_id"] for r in result["results"]}, {"sv_a", "sv_b"})
        self.assertTrue(result["index_used"].startswith("fallback_"))

    def test_index_missing_tag_falls_back_to_items(self):
        item_path = self.root / "items" / "a" / "item.json"
        item = json.loads(item_path.read_text(encoding="utf-8"))
        item["analysis"]["color"]["tags"].append("color:missing")
        item_path.write_text(json.dumps(item), encoding="utf-8")
        result = search(self.root, ["color:missing"])
        self.assertEqual([row["item_id"] for row in result["results"]], ["sv_a"])
        self.assertEqual(result["index_used"], "fallback_tag_missing")

    def test_sidecar_fills_absent_analysis_fields(self):
        item_path = self.root / "items" / "a" / "item.json"
        item = json.loads(item_path.read_text(encoding="utf-8"))
        del item["analysis"]["summary"]
        item_path.write_text(json.dumps(item), encoding="utf-8")
        (self.root / "items" / "a" / "analysis.json").write_text(json.dumps({"summary": "sidecar 夜景"}), encoding="utf-8")
        result = search(self.root, text="sidecar")
        self.assertEqual([row["item_id"] for row in result["results"]], ["sv_a"])

    def test_stable_sort_and_source_unchanged(self):
        before = {path: path.read_bytes() for path in (self.root / "items").glob("*/item.json")}
        result = search(self.root, text="建筑")
        self.assertEqual([r["item_id"] for r in result["results"]], ["sv_b"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})


if __name__ == "__main__":
    unittest.main()
