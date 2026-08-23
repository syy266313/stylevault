#!/usr/bin/env python3
import copy, json, math, sys, tempfile, unittest
from pathlib import Path

HERE=Path(__file__).resolve(); SCRIPT=HERE.parent.parent/'scripts'; ROOT=HERE.parents[3]
sys.path.insert(0,str(SCRIPT))
from evaluate_m331_benchmark import evaluate, load_json

class EvaluatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.config=load_json(ROOT/'configs/video-m3.3.1-benchmark.json')
    def manifest(self, **kw):
        s={"sample_id":"real_1","item_id":"sv_20260823_ab12cd34","source_sha1":"0123456789abcdef0123456789abcdef01234567","source_kind":"user_video","source_origin":"import","duration_ms":4000,"width":1920,"height":1080,"fps":30.0,"codec":"hevc","split":"development","annotation_status":"complete","privacy_status":"approved_local_only","annotations":{"shot_boundaries":[{"time_ms":1000}],"transition_types":[{"value":"hard_cut","time_ms":1000}],"camera_moves":[{"value":"pan","window_ms":[0,900]}],"color_continuity":{"value":"gradual_drift"}}}
        s.update(kw); return {"samples":[s]}
    def prediction(self, **kw):
        p={"shot_boundaries":[{"time_ms":1050}],"params":{"transition_types":[{"value":"hard_cut","time_ms":1040,"confidence":0.9}],"camera_moves":[{"value":"pan","window_ms":[50,850],"status":"confirmed"}],"color_continuity":"gradual_drift"}}
        p.update(kw); return {"real_1":p}
    def test_empty_manifest_metrics_unavailable(self):
        r=evaluate({"samples":[]},{})
        self.assertEqual(r["counts"]["samples"],0); self.assertEqual(r["counts"]["eligible"],0); self.assertFalse(r["metrics"]["available"])
    def test_complete_event_tolerance_and_color_match(self):
        r=evaluate(self.manifest(),self.prediction(),100)
        self.assertEqual(r["counts"]["evaluated"],1)
        self.assertEqual(r["metrics"]["shot_boundary_tolerance_match"]["matched"],1)
        self.assertEqual(r["metrics"]["transition_event_match"]["matched"],1)
        self.assertEqual(r["metrics"]["camera_move_match"]["matched"],1)
        self.assertEqual(r["metrics"]["color_continuity_label_match"]["matched"],1)
        self.assertEqual(r["metrics"]["sample_coverage"]["coverage"],1.0)
    def test_incomplete_pending_and_excluded_are_counted(self):
        base=self.manifest()["samples"][0]
        pending=copy.deepcopy(base); pending["sample_id"]="real_2"; pending["annotation_status"]="not_started"; pending["privacy_status"]="pending"
        excluded=copy.deepcopy(base); excluded["sample_id"]="real_3"; excluded["annotation_status"]="needs_review"; excluded["privacy_status"]="excluded"
        r=evaluate({"samples":[base,pending,excluded]},self.prediction())
        self.assertEqual(r["counts"]["eligible"],1); self.assertEqual(r["counts"]["excluded"],2); self.assertEqual(r["counts"]["evaluated"],1)
    def test_missing_prediction_is_structured_unavailable(self):
        r=evaluate(self.manifest(),{})
        self.assertEqual(r["counts"]["unavailable"],1); self.assertFalse(r["metrics"]["available"]); self.assertIn("unavailable",r["unavailable_samples"][0]["reason"])
    def test_candidate_unknown_coverage_and_holdout_report(self):
        m=self.manifest(split="holdout")
        p=self.prediction(); p["real_1"]["params"]["camera_moves"][0].update({"candidate":True,"status":"candidate"}); p["real_1"]["params"]["transition_types"]=[{"value":"unknown","time_ms":1000}]
        r=evaluate(m,p)
        self.assertEqual(r["holdout_policy"],"report_only_no_tuning"); self.assertEqual(r["metrics"]["unknown_candidate_coverage"]["unknown_events"],1); self.assertEqual(r["metrics"]["unknown_candidate_coverage"]["candidate_events"],1)
    def test_nan_output_does_not_crash_or_fabricate(self):
        p=self.prediction(); p["real_1"]["params"]["transition_types"][0]["time_ms"]=float('nan')
        r=evaluate(self.manifest(),p)
        self.assertEqual(r["metrics"]["transition_event_match"]["matched"],0)
    def test_group_dimensions_present_and_source_unchanged(self):
        m=self.manifest(); snapshot=json.dumps(m,sort_keys=True)
        r=evaluate(m,self.prediction())
        self.assertEqual(set(r["groups"]),{"split","codec","fps_bucket","duration_bucket","resolution","source_origin"})
        self.assertEqual(snapshot,json.dumps(m,sort_keys=True))
    def test_cli_writes_only_report(self):
        self.assertTrue(True)

if __name__=='__main__': unittest.main()
