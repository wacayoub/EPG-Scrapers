#!/usr/bin/env python3
"""Compare exactly two published ElCinema cohorts, without changing them.

Only reports numeric per-ID changes. Never treats moving NOW (future_hours)
as comparable: use absolute programme last-stop timestamps instead.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path

def timestamp(value):
    if not isinstance(value,str):
        raise ValueError("missing timestamp")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("naive timestamp")
    return dt

def load(path):
    obj=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj,dict):
        raise ValueError("non-object report")
    return obj

def report_rows(a):
    feeds=[x for x in a.get("feeds",[]) if isinstance(x,dict) and x.get("feed")=="elcinema.xml.gz"]
    if len(feeds)!=1:
        raise ValueError("missing/duplicate ElCinema audit")
    row=feeds[0]
    per_id=row.get("rows")
    if not isinstance(per_id,list) or len(per_id)!=row.get("channels"):
        raise ValueError("incomplete per-ID audit")
    ids={}
    for x in per_id:
        key=x.get("id")
        if not key or key in ids or x.get("status") not in ("PASS","WARN","FAIL"):
            raise ValueError("invalid duplicate or incomplete ID")
        ids[key]=x
    for k in ("failed_channels","warning_channels","invalid_times","orphan_programmes"):
        if not isinstance(row.get(k),int):
            raise ValueError("missing audit summary "+k)
    if row["failed_channels"]!=sum(x["status"]=="FAIL" for x in ids.values()):
        raise ValueError("failure count is inconsistent")
    return row,ids

def analyze(bmeta,baudit,ameta,aaudit):
    base,before=report_rows(baudit)
    final,after=report_rows(aaudit)
    if set(before)!=set(after):
        raise ValueError("missing or changed channel IDs")
    for meta,audit in ((bmeta,baudit),(ameta,aaudit)):
        if meta.get("label")!="elcinema" or meta.get("channels")!=len(before):
            raise ValueError("publication sidecar identity disagreement")
        if len(meta.get("sha256",""))!=64 or not meta.get("size_bytes"):
            raise ValueError("invalid publication integrity metadata")
        if abs((timestamp(meta["generated_utc"])-timestamp(audit["generated_utc"])).total_seconds())>900:
            raise ValueError("audit from different publication cohort")
    prev=timestamp(bmeta["generated_utc"])
    latest=timestamp(ameta["generated_utc"])
    if latest<=prev:
        return {"decision":"NO_NEW_PUBLICATION","previous_generated_utc":prev.isoformat(),
                "after_generated_utc":latest.isoformat(),"feed_changed":False,
                "release_quality_certified":False}
    converted=[]
    for cid in sorted(before):
        old,new=before[cid],after[cid]
        bs=timestamp(old["latest_stop_utc"]) if old.get("latest_stop_utc") else None
        ns=timestamp(new["latest_stop_utc"]) if new.get("latest_stop_utc") else None
        delta_end=round((ns-bs).total_seconds()/3600,2) if ns and bs else None
        if (old["status"]!=new["status"] or
                delta_end is None or abs(delta_end)>=0.5 or
                abs((new.get("max_gap_minutes") or 0)-(old.get("max_gap_minutes") or 0))>=60):
            converted.append({
                "id":cid,"before_status":old["status"],"after_status":new["status"],
                "last_stop_delta_hours":delta_end,
                "gap_minutes_before":old.get("max_gap_minutes"),
                "gap_minutes_after":new.get("max_gap_minutes"),
            })
    worsened=[x for x in converted if
              x["before_status"]!="FAIL" and x["after_status"]=="FAIL"]
    ended_early=[x for x in converted if x["last_stop_delta_hours"] is not None and
                 x["last_stop_delta_hours"] < -0.5]
    hard=(ameta.get("active_channels")!=bmeta.get("active_channels") or
          final["invalid_times"]>0 or final["orphan_programmes"]>0 or
          final["failed_channels"]>base["failed_channels"] or
          bool(worsened) or bool(ended_early))
    return {
        "decision":"REGRESSION_REVIEW" if hard else "NO_CRITICAL_REGRESSION_DETECTED",
        "previous_generated_utc":prev.isoformat(),
        "after_generated_utc":latest.isoformat(),
        "feed_changed":ameta["sha256"]!=bmeta["sha256"],
        "programme_rows_before":bmeta.get("programmes"),
        "programme_rows_after":ameta.get("programmes"),
        "active_channels_before":bmeta.get("active_channels"),
        "active_channels_after":ameta.get("active_channels"),
        "failed_ids_before":base["failed_channels"],"failed_ids_after":final["failed_channels"],
        "warn_ids_before":base["warning_channels"],"warn_ids_after":final["warning_channels"],
        "regressed_to_fail_count":len(worsened),
        "shorter_last_stop_count":len(ended_early),
        "changed_ids_count":len(converted),
        "changed_ids_first_30":converted[:30],
        "release_quality_certified":False,
        "receiver_modified":False,
        "xmltv_published_by_this_check":False,
    }

def main():
    ap=argparse.ArgumentParser()
    for p in ("before-meta","before-audit","after-meta","after-audit"):
        ap.add_argument("--"+p,required=True)
    args=ap.parse_args()
    report=analyze(*[load(getattr(args,p.replace("-","_"))) for p in (
        "before-meta","before-audit","after-meta","after-audit")])
    print(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2))
    # The purpose is diagnosis; release operators decide after reviewing deltas.
if __name__=="__main__":
    main()
