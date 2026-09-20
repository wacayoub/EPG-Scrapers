#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict direct-feed 48h coverage audit.

A feed passes only when every published channel covers the complete next
48 hours with valid XMLTV times and without a large internal hole. This prevents
"48h" feeds that actually stop tonight/tomorrow from being published.
"""
from __future__ import annotations
import argparse,gzip,json,re
from datetime import datetime,timedelta,timezone
from pathlib import Path
import xml.etree.ElementTree as ET

DT_RE=re.compile(r"^(\d{12}|\d{14})(?:\s*([+-]\d{4}|Z))?")

def dt(v):
    m=DT_RE.match((v or "").strip())
    if not m:return None
    s=m.group(1); fmt="%Y%m%d%H%M%S" if len(s)==14 else "%Y%m%d%H%M"
    x=datetime.strptime(s,fmt)
    off=m.group(2)
    if not off or off=="Z": return x.replace(tzinfo=timezone.utc)
    sign=1 if off[0]=="+" else -1
    mins=sign*(int(off[1:3])*60+int(off[3:5]))
    return x.replace(tzinfo=timezone(timedelta(minutes=mins))).astimezone(timezone.utc)

def root(path):
    raw=Path(path).read_bytes()
    if str(path).endswith(".gz") or raw[:2]==b"\x1f\x8b": raw=gzip.decompress(raw)
    return ET.fromstring(raw)

def audit(path,hours,max_gap_minutes):
    r=root(path); now=datetime.now(timezone.utc); target=now+timedelta(hours=hours)
    channels={}
    for c in r.findall("channel"):
        cid=(c.get("id") or "").strip()
        if cid: channels[cid]=c
    by={cid:[] for cid in channels}; invalid=0; orphan=0
    for p in r.findall("programme"):
        cid=(p.get("channel") or "").strip()
        if cid not in by:
            orphan+=1; continue
        a=dt(p.get("start")); b=dt(p.get("stop"))
        if not a or not b or b<=a:
            invalid+=1; continue
        if b>now-timedelta(hours=2) and a<target+timedelta(hours=6):
            by[cid].append((a,b))
    rows=[]; failed=[]
    gap_limit=timedelta(minutes=max_gap_minutes)
    for cid in sorted(channels,key=str.casefold):
        iv=sorted(by[cid])
        if not iv:
            row={"id":cid,"status":"FAIL","reason":"NO_FUTURE_EPG","future_hours":0.0,"max_gap_minutes":None}
            rows.append(row); failed.append(row); continue
        merged=[]
        for a,b in iv:
            if not merged or a>merged[-1][1]:
                merged.append([a,b])
            elif b>merged[-1][1]:
                merged[-1][1]=b
        # coverage begins at current time; tolerate a small start delay.
        cursor=now
        max_gap=timedelta(0)
        first_gap=max(timedelta(0), merged[0][0]-now)
        max_gap=max(max_gap,first_gap)
        for a,b in merged:
            if b<=cursor: continue
            if a>cursor:
                max_gap=max(max_gap,a-cursor)
            cursor=max(cursor,b)
        future_hours=max(0.0,(cursor-now).total_seconds()/3600.0)
        reasons=[]
        if cursor < target: reasons.append("SHORT_HORIZON")
        if max_gap > gap_limit: reasons.append("INTERNAL_GAP")
        row={
            "id":cid,
            "status":"FAIL" if reasons else "PASS",
            "reason":"+".join(reasons),
            "future_hours":round(future_hours,2),
            "latest_stop_utc":cursor.isoformat(),
            "max_gap_minutes":round(max_gap.total_seconds()/60.0,1),
            "programmes":len(iv),
        }
        rows.append(row)
        if reasons: failed.append(row)
    return {
        "feed":Path(path).name,
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "required_hours":hours,
        "max_gap_minutes_allowed":max_gap_minutes,
        "channels":len(channels),
        "invalid_times":invalid,
        "orphan_programmes":orphan,
        "failed_channels":len(failed),
        "status":"FAIL" if failed or invalid or orphan or not channels else "PASS",
        "rows":rows,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("feeds",nargs="+")
    ap.add_argument("--hours",type=float,default=48.0)
    ap.add_argument("--max-gap-minutes",type=int,default=90)
    ap.add_argument("--report",required=True)
    a=ap.parse_args()
    reports=[audit(p,a.hours,a.max_gap_minutes) for p in a.feeds]
    out={"generated_utc":datetime.now(timezone.utc).isoformat(),"required_hours":a.hours,"feeds":reports}
    Path(a.report).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    failed=[]
    for r in reports:
        print("%s %s channels=%d failed=%d invalid=%d orphan=%d"%(
            r["status"],r["feed"],r["channels"],r["failed_channels"],r["invalid_times"],r["orphan_programmes"]))
        for row in r["rows"]:
            if row["status"]=="FAIL":
                print("  FAIL %-45s horizon=%6.2fh gap=%s reason=%s"%(
                    row["id"],row["future_hours"],row["max_gap_minutes"],row["reason"]))
        if r["status"]!="PASS": failed.append(r["feed"])
    if failed:
        print("DIRECT_48H_AUDIT FAIL:",", ".join(failed))
        return 2
    print("DIRECT_48H_AUDIT PASS: all channels cover the next %.1f hours"%a.hours)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
