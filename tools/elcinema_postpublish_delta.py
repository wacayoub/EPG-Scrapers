#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare successive *published* ElCinema reports after midnight parser fix.

Both inputs are historical Git revisions of a provider's own source metadata.
This emits aggregate/per-ID changes only, never copyrighted programme text,
and is NOT permission to publish otherwise unlicensed EPG listings.

The moving 48h window makes a raw future_hours delta misleading, so compare
absolute latest-stop UTC. Never claim source recovery based only on tests.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

def _date(raw):
    if not isinstance(raw,str):
        raise ValueError("missing timestamp")
    d=datetime.fromisoformat(raw.replace("Z","+00:00"))
    if d.tzinfo is None:
        raise ValueError("naive timestamp")
    return d.astimezone(timezone.utc)

def _audit(x):
    if not isinstance(x,dict):
        raise ValueError("audit not object")
    feeds=[f for f in x.get("feeds",()) if isinstance(f,dict) and f.get("feed")=="elcinema.xml.gz"]
    if len(feeds)!=1:
        raise ValueError("missing/unexpected ElCinema audit row")
    f=feeds[0]
    rows=f.get("rows")
    if not isinstance(rows,list) or not 60<=len(rows)<=150:
        raise ValueError("unexpected number of ElCinema channel rows")
    ids={}
    for v in rows:
        if not isinstance(v,dict):
            raise ValueError("invalid channel row")
        cid=v.get("id")
        if not isinstance(cid,str) or not cid.strip() or cid in ids:
            raise ValueError("missing/duplicate ID")
        if v.get("status") not in ("PASS","WARN","FAIL"):
            raise ValueError("invalid audit channel status")
        ids[cid]=v
    if not isinstance(f.get("failed_channels"),int) or f["failed_channels"]!=sum(x["status"]=="FAIL" for x in rows):
        raise ValueError("failed status summary mismatch")
    if not isinstance(f.get("warning_channels"),int) or f["warning_channels"]!=sum(x["status"]=="WARN" for x in rows):
        raise ValueError("warning summary mismatch")
    return f,ids

def compare(old_meta,old_report,new_meta,new_report):
    old,prev=_audit(old_report)
    new,cur=_audit(new_report)
    if set(prev)!=set(cur):
        raise ValueError("ElCinema channel identity regression")
    for metadata,report in ((old_meta,old_report),(new_meta,new_report)):
        if metadata.get("channels")!=len(cur) or metadata.get("active_channels")>metadata.get("channels"):
            raise ValueError("feed/channel metadata mismatch")
        if abs((_date(report["generated_utc"])-_date(metadata["generated_utc"])).total_seconds())>15*60:
            raise ValueError("source/audit cohorts are incoherent")
        checksum=metadata.get("sha256")
        if not isinstance(checksum,str) or len(checksum)!=64:
            raise ValueError("missing feed fingerprint")
    if _date(new_meta["generated_utc"])<=_date(old_meta["generated_utc"]):
        raise ValueError("comparison not an increasing publication pair")
    old_bad={cid for cid,row in prev.items() if row["status"]=="FAIL"}
    new_bad={cid for cid,row in cur.items() if row["status"]=="FAIL"}
    old_short={cid for cid,row in prev.items() if row.get("reason")=="TOO_SHORT+INTERNAL_GAP"}
    new_short={cid for cid,row in cur.items() if row.get("reason")=="TOO_SHORT+INTERNAL_GAP"}
    worsened=[]
    extended=[]
    for cid,was in prev.items():
        after=cur[cid]
        pre=was.get("latest_stop_utc")
        post=after.get("latest_stop_utc")
        if pre and post:
            delta=(_date(post)-_date(pre)).total_seconds()/3600
            if delta < -1:
                worsened.append(cid)
            if delta > 1:
                extended.append(cid)
    improvements=sorted(old_bad-new_bad)
    failures=sorted(new_bad-old_bad)
    ratio=100*len(cur)/len(prev)
    return {
       "audit":"ElCinema subsequent-publication comparison only",
       "old_generated_utc":old_meta["generated_utc"],
       "new_generated_utc":new_meta["generated_utc"],
       "same_channel_ids":True,"channel_count":len(cur),"programme_count_before":old_meta["programmes"],
       "programme_count_after":new_meta["programmes"],
       "currently_on_air_before":old_meta.get("currently_on_air_channels"),
       "currently_on_air_after":new_meta.get("currently_on_air_channels"),
       "48h_failed_before":len(old_bad),"48h_failed_after":len(new_bad),
       "short_plus_gap_before":len(old_short),"short_plus_gap_after":len(new_short),
       "previous_failed_ids_recovered":improvements,
       "new_failed_ids":failures,
       "source_stop_extended_ids":sorted(extended),
       "source_stop_shortened_ids":sorted(worsened),
       "source_quality_improved":bool(improvements) and not failures and not worsened,
       "safe_to_claim_all_48h_recovered":not new_bad,
       "result_status":("IMPROVED" if improvements and not failures and not worsened
                        else "MIXED_OR_REGRESSION" if failures or worsened
                        else "NO_VERIFIED_48H_FAILURE_RECOVERY"),
       "receiver_modified":False,"published_feeds_modified":False,
       "not_a_native_epgcache_validation":True,
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("old-meta","old-report","new-meta","new-report"):
        ap.add_argument("--"+name,required=True)
    opts=ap.parse_args()
    kwargs={k.replace("-","_"):json.loads(Path(getattr(opts,k.replace("-","_"))).read_text(encoding="utf8"))
            for k in ("old-meta","old-report","new-meta","new-report")}
    print("ELCINEMA_PUBLICATION_DELTA",json.dumps(compare(
        kwargs["old_meta"],kwargs["old_report"],kwargs["new_meta"],kwargs["new_report"]
    ),sort_keys=True,ensure_ascii=False))
if __name__=="__main__":
    main()
