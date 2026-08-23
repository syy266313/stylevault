#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
from evaluate_regression import evaluate, snapshot  # noqa: E402


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "items" / "a").mkdir(parents=True)
        (self.root / "indexes").mkdir()
        item = {
            "id": "sv_20260823_ab12cd34", "type": "image", "collections": ["golden-dataset"],
            "analysis": {"status": "done", "style": {"tags": ["style:minimal"]}, "color": {"tags": ["color:low-sat"]}, "summary": "低饱和夜景", "editing_rules": [{"aspect": "color", "rule": "保持低饱和"}], "preference": 5}
        }
        (self.root / "items" / "a" / "item.json").write_text(json.dumps(item), encoding="utf-8")
        (self.root / "indexes" / "tags.json").write_text(json.dumps({"tags": {"style:minimal": [item["id"]], "color:low-sat": [item["id"]]}}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, args, expect):
        return {"version": "test", "queries": [{"id": "q", "args": args, "expect": expect}]}

    def test_durable_properties_and_read_only_snapshot(self):
        config = self.config({"tags": ["style:minimal"], "mode": "and", "item_type": "image", "collection": "golden-dataset", "preference_min": 0.7}, {"non_empty": True})
        before = snapshot(self.root)
        report = evaluate(self.root, config)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["source_files_unchanged"])
        self.assertEqual(before, snapshot(self.root))
        self.assertTrue(report["queries"][0]["filters_respected"])

    def test_empty_query_expected_shape(self):
        config = self.config({"tags": ["style:missing"]}, {"empty": True})
        report = evaluate(self.root, config)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["queries"][0]["count"], 0)


if __name__ == "__main__":
    unittest.main()
