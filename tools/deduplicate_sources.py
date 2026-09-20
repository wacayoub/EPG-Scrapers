#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-source duplicate arbitration for published EPG feeds.

Works only on existing feeds/*.xml.gz. It never scrapes upstream sites.
For each logical channel appearing in more than one source, it compares:
- source speciality/directness;
- Arabic title/description quality;
- description coverage;
- future coverage and event count;
then keeps one winner and removes the losers from lower-quality feeds.

A full JSON/Markdown audit is written before publication.
"""
from __future__ import annotations
import argparse, gzip, json, re, shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

SOURCES=("morocco","bein","osn","sport24","elcinema")
AR=re.compile(r"[\u0600-\u06FF]")

def read_root(path:Path):
    b=path.read_bytes()
    if b[:2]==b"\x1f\x8b": b=gzip.decompress(b)
    return ET.fromstring(b)

def write_root(path:Path,root):
    ET.indent(root,space="  ")
    b=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gzip.compress(b,9,mtime=0))

def text_of(node,tag):
    for x in node.findall(tag):
        t=(x.text or "").strip()
        if t: return t
    return ""

def norm_name(s):
    s=(s or "").casefold()
    s=re.sub(r"\b(hd|sd|uhd|4k|tv|channel)\b"," ",s)
    s=re.sub(r"[^a-z0-9\u0600-\u06ff]+","",s)
    return s

def canonical_id(cid,name):
    # Exact XMLTV family first: strip region/quality suffix only.
    base=(cid or "").split("@",1)[0].casefold()
    if cid.startswith("sport24."):
        n=norm_name(name)
        aliases={
            "abudhabisports1":"abudhabisports1.ae",
            "abudhabisports2":"abudhabisports2.ae",
            "abudhabisports3":"abudhabisports3.ae",
            "abudhabisports4":"abudhabisports4.ae",
            "dubaisports1":"dubaisports1.ae",
            "dubaisports2":"dubaisports2.ae",
            "thmanyah1":"thmanyah1.sa",
            "thmanyah2":"thmanyah2.sa",
            "thmanyah3":"thmanyah3.sa",
            "beinsports":"beinsports.qa",
            "beinsportsfree":"beinsports.qa",
            "beinsports1":"beinsports1.qa",
            "beinsports2":"beinsports2.qa",
            "beinsports3":"beinsports3.qa",
            "beinsports4":"beinsports4.qa",
            "beinsports5":"beinsports5.qa",
            "beinsports6":"beinsports6.qa",
            "beinsports7":"beinsports7.qa",
            "beinsports8":"beinsports8.qa",
            "beinsports9":"beinsports9.qa",
            "beinsportsnews":"beinsportsnews.qa",
        }
        return aliases.get(n,base)
    return base

def specialty_bonus(source,canon):
    c=canon.casefold()
    if source=="morocco" and any(x in c for x in ("alaoula","arryadia","2m","medi1","tamazight","assadisa","almaghribiya","arrabiaa","aflam","chada")):
        return 70
    if source=="bein" and c.startswith("beinsports"):
        return 70
    if source=="osn" and c.startswith("osn"):
        return 70
    if source=="sport24" and any(x in c for x in ("abudhabisports","dubaisports","thmanyah")):
        return 70
    # Arabic entertainment/general channels are usually richer in ElCinema.
    if source=="elcinema":
        return 18
    # beIN entertainment is not automatically preferred over a richer Arabic grid.
    if source=="bein" and c.startswith(("beinmovies","beinseries","beindrama")):
        return 8
    return 0

def metrics(root,cid):
    now=datetime.now(timezone.utc)
    rows=[p for p in root.findall("programme") if (p.get("channel") or "")==cid]
    titles=[text_of(p,"title") for p in rows]
    descs=[text_of(p,"desc") for p in rows]
    def pct(vals,pred):
        vals=[v for v in vals if v]
        return round(100*sum(1 for v in vals if pred(v))/len(vals),1) if vals else 0.0
    future=0
    last=None
    for p in rows:
        raw=(p.get("stop") or p.get("start") or "")[:14]
        try:
            dt=datetime.strptime(raw,"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            if dt>now: future+=1
            if last is None or dt>last: last=dt
        except Exception: pass
    future_hours=max(0.0,(last-now).total_seconds()/3600) if last else 0.0
    return {
        "programmes":len(rows),
        "future_programmes":future,
        "future_hours":round(future_hours,1),
        "desc_pct":round(100*sum(1 for d in descs if d)/len(rows),1) if rows else 0.0,
        "arabic_title_pct":pct(titles,lambda x: bool(AR.search(x))),
        "arabic_desc_pct":pct(descs,lambda x: bool(AR.search(x))),
    }

def score(source,canon,m):
    # Quality-first, with strong specialist-source preference where appropriate.
    return round(
        specialty_bonus(source,canon)
        + min(m["future_hours"],48)/48*18
        + min(m["future_programmes"],40)/40*12
        + m["desc_pct"]/100*18
        + m["arabic_title_pct"]/100*18
        + m["arabic_desc_pct"]/100*16,
        2
    )

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--feeds-dir",default="feeds")
    ap.add_argument("--output-dir",default="output/dedup")
    ap.add_argument("--report-json",default="reports/source-winners.json")
    ap.add_argument("--report-md",default="reports/source-winners.md")
    a=ap.parse_args()
    feeds=Path(a.feeds_dir); out=Path(a.output_dir)
    roots={}
    channel_nodes={}
    entries=defaultdict(list)

    for source in SOURCES:
        p=feeds/f"{source}.xml.gz"
        if not p.exists(): continue
        root=read_root(p); roots[source]=root
        channel_nodes[source]={}
        for ch in root.findall("channel"):
            cid=(ch.get("id") or "").strip()
            if not cid: continue
            name=text_of(ch,"display-name") or cid
            channel_nodes[source][cid]=ch
            canon=canonical_id(cid,name)
            m=metrics(root,cid)
            entries[canon].append({
                "source":source,"id":cid,"name":name,
                "metrics":m,"score":score(source,canon,m),
                "specialty_bonus":specialty_bonus(source,canon),
            })

    duplicates=[]
    losers=defaultdict(set)
    winners={}
    for canon,opts in sorted(entries.items()):
        if len(opts)<2: continue
        ranked=sorted(opts,key=lambda x:(x["score"],x["metrics"]["future_programmes"],x["metrics"]["programmes"]),reverse=True)
        winner=ranked[0]
        winners[canon]=winner
        for x in ranked[1:]: losers[x["source"]].add(x["id"])
        duplicates.append({"canonical":canon,"winner":winner,"candidates":ranked})

    # Write pruned copies of every existing source feed.
    for source,root in roots.items():
        drop=losers[source]
        if drop:
            for ch in list(root.findall("channel")):
                if (ch.get("id") or "") in drop: root.remove(ch)
            for p in list(root.findall("programme")):
                if (p.get("channel") or "") in drop: root.remove(p)
        write_root(out/f"{source}.xml.gz",root)

    report={
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "duplicate_groups":len(duplicates),
        "losers_removed":{s:len(v) for s,v in losers.items() if v},
        "duplicates":duplicates,
    }
    Path(a.report_json).parent.mkdir(parents=True,exist_ok=True)
    Path(a.report_json).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    lines=["# Cross-source EPG winners","",f"Duplicate groups: **{len(duplicates)}**","",
           "| Channel | Winner | Score | Other sources |","|---|---|---:|---|"]
    for d in duplicates:
        w=d["winner"]
        others=", ".join(f'{x["source"]} ({x["score"]})' for x in d["candidates"][1:])
        lines.append(f'| {w["name"]} | **{w["source"]}** | {w["score"]} | {others} |')
    Path(a.report_md).write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({
        "duplicate_groups":len(duplicates),
        "losers_removed":report["losers_removed"],
        "winners_by_source":dict((s,sum(1 for x in winners.values() if x["source"]==s)) for s in SOURCES)
    },ensure_ascii=False))
    return 0

if __name__=="__main__": raise SystemExit(main())
