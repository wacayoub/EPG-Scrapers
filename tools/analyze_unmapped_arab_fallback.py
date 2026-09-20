#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze all fallback channels that are not yet mapped in production.

Input:
  reports/arab-fallback-all-channels.csv
  feeds/*.xml.gz

Output:
  reports/unmapped-arab-fallback.json
  reports/unmapped-arab-fallback.csv
  reports/unmapped-arab-fallback.md

This is analysis only: no production feed is modified.
"""
from __future__ import annotations
import csv, gzip, json, re, unicodedata
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

IN=Path("reports/arab-fallback-all-channels.csv")
REPORT=Path("reports")

ARABIC_RE=re.compile(r"[\u0600-\u06ff]")
NONWORD_RE=re.compile(r"[^\w\u0600-\u06ff]+",re.UNICODE)

ALIASES={
    "ad sport":"abu dhabi sport",
    "ad sports":"abu dhabi sports",
    "bein movie 1":"bein movies 1",
    "bein movie 2":"bein movies 2",
    "bein sports en1":"bein sports 1 english",
    "bbc arabic":"bbc arabic news",
    "cnn hd":"cnn international",
    "disney channel hd":"disney channel",
    "sharjat tv":"sharjah tv",
}

SOURCE_COUNTRY={
    "AE1":"UAE",
    "EG1":"Egypt",
    "SA1":"Saudi Arabia",
    "SA2":"Saudi Arabia",
    "AR1":"Arab region",
    "BEIN1":"MENA",
    "ALJAZEERA1":"Qatar/MENA",
    "egypt1":"Egypt",
    "egypt2":"Egypt",
    "qatar1":"Qatar","qatar2":"Qatar","qatar3":"Qatar",
    "qatar4":"Qatar","qatar5":"Qatar","qatar6":"Qatar",
    "saudiarabia1":"Saudi Arabia","saudiarabia2":"Saudi Arabia",
    "saudiarabia3":"Saudi Arabia","saudiarabia4":"Saudi Arabia",
    "saudiarabia5":"Saudi Arabia",
    "uae6":"UAE",
}

SOURCE_PRIORITY={
    "openepg":2,
    "epgshare":1,
}

def norm(s:str)->str:
    s=unicodedata.normalize("NFKC",s or "").casefold()
    s=s.replace("&"," and ")
    s=re.sub(r"\b(?:hd|sd|fhd|uhd|4k)\b"," ",s)
    s=re.sub(r"\b(?:tv|channel)\b"," ",s)
    s=NONWORD_RE.sub(" ",s)
    s=" ".join(s.split())
    return ALIASES.get(s,s)

def load_xml(path):
    data=path.read_bytes()
    if data[:2]==b"\x1f\x8b":
        data=gzip.decompress(data)
    return ET.fromstring(data)

def production_catalog():
    ids=set()
    names=defaultdict(set)
    by_id={}
    for p in Path("feeds").glob("*.xml.gz"):
        try:
            root=load_xml(p)
        except Exception:
            continue
        feed=p.name
        for ch in root.findall("channel"):
            cid=(ch.get("id") or "").strip()
            if not cid: continue
            ids.add(cid)
            dnames=[(x.text or "").strip() for x in ch.findall("display-name") if (x.text or "").strip()]
            if not dnames:
                dnames=[cid]
            by_id[cid]={"feed":feed,"names":dnames}
            for dn in dnames:
                n=norm(dn)
                if n:
                    names[n].add(cid)
    return ids,names,by_id

def score(r):
    # analysis ranking only, not a publication decision
    fp=min(int(float(r["future_programmes"])),250)
    fh=min(float(r["future_hours"]),168.0)
    desc=float(r["desc_pct"])
    return round(fp*1.0 + fh*1.5 + desc*0.8 + SOURCE_PRIORITY.get(r["provider"],0)*10,2)

def main():
    if not IN.exists():
        raise SystemExit(f"missing {IN}; run Build Arab fallback analysis first")

    prod_ids,prod_names,prod_by_id=production_catalog()

    rows=[]
    with IN.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["future_programmes"]=int(float(r["future_programmes"] or 0))
            r["future_hours"]=float(r["future_hours"] or 0)
            r["desc_pct"]=float(r["desc_pct"] or 0)
            if r["future_programmes"]<=0:
                continue
            r["country"]=SOURCE_COUNTRY.get(r["source"],"Unknown/Regional")
            r["norm_name"]=norm(r["name"])
            r["quality_score"]=score(r)
            if r["id"] in prod_ids:
                r["status"]="EXACT_ID_ALREADY_PRESENT"
                r["existing_ids"]=r["id"]
            elif r["norm_name"] and r["norm_name"] in prod_names:
                r["status"]="NAME_COLLISION_REVIEW"
                r["existing_ids"]=";".join(sorted(prod_names[r["norm_name"]]))
            else:
                r["status"]="UNMAPPED"
                r["existing_ids"]=""
            rows.append(r)

    exact=[r for r in rows if r["status"]=="EXACT_ID_ALREADY_PRESENT"]
    collision=[r for r in rows if r["status"]=="NAME_COLLISION_REVIEW"]
    unmapped=[r for r in rows if r["status"]=="UNMAPPED"]

    # Group aliases/alternatives by normalized name, else by raw XMLTV id.
    groups=defaultdict(list)
    for r in unmapped:
        key=r["norm_name"] or r["id"].casefold()
        groups[key].append(r)

    winners=[]
    alternatives=[]
    for key,arr in groups.items():
        arr=sorted(arr,key=lambda r:(r["quality_score"],r["future_programmes"],r["desc_pct"]),reverse=True)
        win=dict(arr[0])
        win["alternatives"]=len(arr)-1
        win["alternative_sources"]=";".join(f'{x["provider"]}:{x["source"]}:{x["id"]}' for x in arr[1:])
        winners.append(win)
        for x in arr[1:]:
            alternatives.append(x)
    winners.sort(key=lambda r:(r["quality_score"],r["future_programmes"],r["desc_pct"]),reverse=True)

    REPORT.mkdir(exist_ok=True)

    fields=["country","name","id","provider","source","future_programmes","future_hours","desc_pct",
            "quality_score","alternatives","alternative_sources","url"]
    with (REPORT/"unmapped-arab-fallback.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        for r in winners:
            w.writerow({k:r.get(k,"") for k in fields})

    review_fields=["status","name","id","provider","source","country","existing_ids",
                   "future_programmes","future_hours","desc_pct","quality_score","url"]
    with (REPORT/"unmapped-arab-fallback-review.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=review_fields)
        w.writeheader()
        for r in sorted(collision,key=lambda x:x["quality_score"],reverse=True):
            w.writerow({k:r.get(k,"") for k in review_fields})

    by_country=Counter(r["country"] for r in winners)
    by_provider=Counter(r["provider"] for r in winners)

    summary={
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "production_ids":len(prod_ids),
        "fallback_active_rows":len(rows),
        "exact_id_already_present_rows":len(exact),
        "name_collision_review_rows":len(collision),
        "unmapped_rows_before_name_dedup":len(unmapped),
        "unique_unmapped_candidates":len(winners),
        "duplicate_alternative_rows_collapsed":len(alternatives),
        "by_country":dict(by_country),
        "by_provider":dict(by_provider),
        "top_candidates":[
            {k:r.get(k) for k in ("country","name","id","provider","source","future_programmes","future_hours","desc_pct","quality_score","alternatives")}
            for r in winners[:100]
        ]
    }
    (REPORT/"unmapped-arab-fallback.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    lines=[
        "# Unmapped Arab fallback analysis","",
        f"Production channel IDs: **{len(prod_ids)}**  ",
        f"Active fallback rows analyzed: **{len(rows)}**  ",
        f"Exact IDs already present: **{len(exact)}**  ",
        f"Name collisions requiring review: **{len(collision)}**  ",
        f"Unmapped rows before dedup: **{len(unmapped)}**  ",
        f"Unique unmapped candidates: **{len(winners)}**  ",
        f"Alternative duplicate rows collapsed: **{len(alternatives)}**","",
        "## By country / region","",
        "| Country / region | Unique unmapped |",
        "|---|---:|",
    ]
    for c,n in by_country.most_common():
        lines.append(f"| {c} | {n} |")
    lines += ["","## Top 100 candidates","",
              "| Country | Channel | XMLTV ID | Source | Future programmes | Future h | Desc % | Score | Alternatives |",
              "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for r in winners[:100]:
        name=str(r["name"]).replace("|","/")
        lines.append(
            f'| {r["country"]} | {name} | {r["id"]} | {r["provider"]}:{r["source"]} | '
            f'{r["future_programmes"]} | {r["future_hours"]:.1f} | {r["desc_pct"]:.1f} | '
            f'{r["quality_score"]:.1f} | {r["alternatives"]} |'
        )
    (REPORT/"unmapped-arab-fallback.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

    print(json.dumps(summary,ensure_ascii=False))
    print("UNMAPPED_UNIQUE",len(winners))
    print("NAME_COLLISION_REVIEW",len(collision))
    print("EXACT_ALREADY_PRESENT",len(exact))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
