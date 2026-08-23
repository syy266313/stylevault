#!/usr/bin/env python3
"""Report-only evaluator for the independent M3.3.1 benchmark."""
import argparse, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_GROUPS = ("split", "codec", "fps_bucket", "duration_bucket", "resolution", "source_origin")

def load_json(path):
    with open(path, encoding="utf-8") as f: return json.load(f)

def finite(v): return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def bucket_fps(v):
    if not finite(v): return "unknown"
    return "<24" if v < 24 else "24-29.99" if v < 30 else "30-59.99" if v < 60 else "60+"

def bucket_duration(v):
    if not isinstance(v, int) or v <= 0: return "unknown"
    return "<10s" if v < 10000 else "10-60s" if v < 60000 else "60s+"

def group_value(sample, dim):
    if dim == "resolution": return f"{sample.get('width','?')}x{sample.get('height','?')}"
    if dim == "fps_bucket": return bucket_fps(sample.get("fps"))
    if dim == "duration_bucket": return bucket_duration(sample.get("duration_ms"))
    return str(sample.get(dim, "unknown"))

def point(event):
    if not isinstance(event, dict): return None
    if finite(event.get("time_ms")): return float(event["time_ms"])
    window = event.get("window_ms")
    if isinstance(window, list) and len(window) == 2 and all(finite(x) for x in window): return (float(window[0])+float(window[1]))/2
    return None

def label(event):
    if isinstance(event, str): return event
    return event.get("value", event.get("label")) if isinstance(event, dict) else None

def events(obj, field):
    if not isinstance(obj, dict): return []
    candidates = obj.get(field)
    if candidates is None: candidates = obj.get("params", {}).get(field) if isinstance(obj.get("params"), dict) else None
    return candidates if isinstance(candidates, list) else []

def metric(name, matched, expected, predicted=None):
    predicted = expected if predicted is None else predicted
    return {"name": name, "matched": matched, "expected": expected, "predicted": predicted,
            "coverage": round(matched / expected, 4) if expected else None,
            "available": bool(expected)}

def match_events(expected, predicted, tolerance_ms):
    used=set(); matches=0
    for exp in expected:
        ep=point(exp); el=label(exp)
        if ep is None or el in (None, "unknown"): continue
        choices=[]
        for i, pred in enumerate(predicted):
            if i in used or label(pred) != el: continue
            pp=point(pred)
            if pp is not None and abs(ep-pp) <= tolerance_ms: choices.append((abs(ep-pp), i))
        if choices:
            _, i=min(choices); used.add(i); matches += 1
    return matches

def match_metric(name, expected, predicted, tolerance_ms):
    usable=[e for e in expected if label(e) not in (None, "unknown")]
    usable_pred=[e for e in predicted if label(e) not in (None, "unknown")]
    return metric(name, match_events(usable, usable_pred, tolerance_ms), len(usable), len(usable_pred))

def boundary_metric(expected, prediction, tolerance_ms):
    def times(v):
        out=[]
        for x in v if isinstance(v,list) else []:
            x=x.get("time_ms") if isinstance(x,dict) else x
            if finite(x): out.append(float(x))
        return out
    a=times(expected); b=times(prediction); used=set(); matched=0
    for x in a:
        choices=[(abs(x-y),i) for i,y in enumerate(b) if i not in used and abs(x-y)<=tolerance_ms]
        if choices: _,i=min(choices); used.add(i); matched+=1
    return metric("shot_boundary_tolerance_match", matched, len(a), len(b))

def prediction_for(predictions, sample_id):
    if not isinstance(predictions, dict): return None
    value=predictions.get(sample_id)
    if value is None and isinstance(predictions.get("predictions"), dict): value=predictions["predictions"].get(sample_id)
    return value

def evaluate_sample(sample, prediction, tolerance_ms):
    ann=sample.get("annotations") or {}; pred=prediction if isinstance(prediction,dict) else {}
    pparams=pred.get("rhythm", {}).get("params", {}) if isinstance(pred.get("rhythm"),dict) else {}
    if isinstance(pred.get("params"),dict): pparams={**pparams, **pred["params"]}
    color=ann.get("color_continuity") if isinstance(ann.get("color_continuity"),dict) else {}
    pcolor=pparams.get("color_continuity", pred.get("color_continuity"))
    pcolor=label(pcolor)
    predicted_boundaries=pred.get("shot_boundaries", pparams.get("shot_boundaries", []))
    out={"shot_boundary_tolerance_match":boundary_metric(ann.get("shot_boundaries",[]), predicted_boundaries, tolerance_ms),
         "transition_event_match":match_metric("transition_event_match", events(ann,"transition_types"), events(pparams,"transition_types") or events(pred,"transition_types"), tolerance_ms),
         "camera_move_match":match_metric("camera_move_match", events(ann,"camera_moves"), events(pparams,"camera_moves") or events(pred,"camera_moves"), tolerance_ms),
         "color_continuity_label_match": {"name":"color_continuity_label_match", "matched":int(bool(color.get("value") and color.get("value") != "unknown" and pcolor == color.get("value"))), "expected":int(bool(color.get("value") and color.get("value") != "unknown")), "predicted":int(bool(pcolor and pcolor != "unknown")), "available":bool(color.get("value") and color.get("value") != "unknown")}}
    all_pred=events(pparams,"transition_types")+events(pparams,"camera_moves")
    unknown=sum(1 for x in all_pred if label(x)=="unknown" or x.get("status")=="unknown" if isinstance(x,dict))
    candidate=sum(1 for x in all_pred if isinstance(x,dict) and (x.get("candidate") is True or x.get("status")=="candidate"))
    out["unknown_candidate_coverage"]={"name":"unknown_candidate_coverage","predicted_events":len(all_pred),"unknown_events":unknown,"candidate_events":candidate,"coverage":round((unknown+candidate)/len(all_pred),4) if all_pred else None,"available":bool(prediction)}
    out["failure_examples"]=[]
    for key,val in out.items():
        if key.endswith("match") and val.get("available") and val.get("matched") < val.get("expected"): out["failure_examples"].append(key)
    return out

def aggregate(rows):
    result={}
    for name in ("shot_boundary_tolerance_match","transition_event_match","camera_move_match","color_continuity_label_match"):
        vals=[r[name] for r in rows if r.get(name,{}).get("available")]
        matched=sum(x["matched"] for x in vals); expected=sum(x["expected"] for x in vals); predicted=sum(x["predicted"] for x in vals)
        result[name]=metric(name,matched,expected,predicted)
    cov=[r["unknown_candidate_coverage"] for r in rows if r.get("unknown_candidate_coverage",{}).get("available")]
    result["unknown_candidate_coverage"]={"name":"unknown_candidate_coverage","predicted_events":sum(x["predicted_events"] for x in cov),"unknown_events":sum(x["unknown_events"] for x in cov),"candidate_events":sum(x["candidate_events"] for x in cov),"available":bool(cov)}
    return result

def evaluate(manifest, predictions, tolerance_ms=100):
    samples=manifest.get("samples",[]) if isinstance(manifest,dict) else []
    eligible=[s for s in samples if isinstance(s,dict) and s.get("privacy_status")=="approved_local_only" and s.get("annotation_status")=="complete"]
    excluded=[s for s in samples if s not in eligible]
    rows=[]; failures=[]; unavailable=[]
    for s in eligible:
        pred=prediction_for(predictions,s.get("sample_id"))
        if pred is None:
            unavailable.append({"sample_id":s.get("sample_id"),"reason":"detector output unavailable; media or prediction missing"}); continue
        row=evaluate_sample(s,pred,tolerance_ms); rows.append(row)
        if row["failure_examples"]: failures.append({"sample_id":s.get("sample_id"),"metrics":row["failure_examples"]})
    groups={}
    for dim in DEFAULT_GROUPS:
        buckets=defaultdict(list)
        for s in eligible:
            pred=prediction_for(predictions,s.get("sample_id"))
            if pred is not None: buckets[group_value(s,dim)].append(evaluate_sample(s,pred,tolerance_ms))
        groups[dim]={k:{"sample_count":len(v),"metrics":aggregate(v)} for k,v in sorted(buckets.items())}
    metrics = aggregate(rows) if rows else {"available":False,"reason":"metrics unavailable: no eligible detector outputs"}
    metrics["sample_coverage"] = {"name":"sample_coverage", "evaluated":len(rows), "eligible":len(eligible), "coverage":round(len(rows)/len(eligible),4) if eligible else None, "available":bool(eligible)}
    return {"benchmark":"M3.3.1","acceptance_role":"benchmark_report_only","holdout_policy":"report_only_no_tuning","counts":{"samples":len(samples),"eligible":len(eligible),"excluded":len(excluded),"evaluated":len(rows),"unavailable":len(unavailable),"excluded_by_status":dict(Counter((s.get("privacy_status"),s.get("annotation_status")) for s in excluded))},"annotation_completeness":{"complete":sum(s.get("annotation_status")=="complete" for s in samples),"total":len(samples),"ratio":round(sum(s.get("annotation_status")=="complete" for s in samples)/len(samples),4) if samples else None},"metrics":metrics,"groups":groups,"unavailable_samples":unavailable,"failure_examples":failures[:50]}

def main(argv=None):
    p=argparse.ArgumentParser(description="Evaluate M3.3.1 real-video benchmark; report only")
    p.add_argument("--manifest",required=True); p.add_argument("--predictions",required=True); p.add_argument("--tolerance-ms",type=float,default=100); p.add_argument("--output")
    args=p.parse_args(argv)
    try:
        manifest=load_json(args.manifest); predictions=load_json(args.predictions)
        if not finite(args.tolerance_ms) or args.tolerance_ms < 0: raise ValueError("tolerance-ms must be finite and non-negative")
        report=evaluate(manifest,predictions,args.tolerance_ms); text=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
        if args.output: Path(args.output).write_text(text,encoding="utf-8")
        print(text); return 0
    except (OSError,json.JSONDecodeError,TypeError,ValueError) as exc:
        print(json.dumps({"ok":False,"error":str(exc),"metrics":{"available":False,"reason":"unavailable"}},ensure_ascii=False)); return 2
if __name__ == "__main__": raise SystemExit(main())
