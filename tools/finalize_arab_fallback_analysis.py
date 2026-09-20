#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finalize fallback duplicate analysis and zero-EPG blacklist.

Analysis-only. It does not modify production feeds.

Rules:
- Healthy production/direct IDs always win over fallback candidates.
- Same fallback channel appearing in several source files is grouped by
  normalized channel name / canonical ID.
- Winner is selected by future coverage, programme count, description
  completeness, language fitness, and provider preference.
- IDs with zero future programmes are placed in an auto-blacklist.
- Source files with zero active channels or invalid XML are source-blacklisted.
"""
from __future__ import annotations
import csv, json, re, unicodedata
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path

ALL=Path("reports/arab-fallback-all-channels.csv")
UNMAPPED=Path("reports/unmapped-arab-fallback.csv")
HEALTH=Path("reports/arab-fallback-health.json")
OUT=Path("reports")

AR=re.compile(r"[\u0600-\u06ff]")
LATAM_BAD=re.compile(r"\b(argentina|latinoam[eé]rica|latin america|pakapaka|tooncast)\b",re.I)
EXCLUDED_SOURCE_KEYS={("epgshare","AR1")}
PREFIX_RE=re.compile(r"^(?:en|ar)\s*:\s*",re.I)

ALIASES={
    "mbc 3":"mbc3","mbc3":"mbc3",
    "mbc 1":"mbc1","mbc1":"mbc1",
    "mbc action":"mbc action",
    "mbc masr hd":"mbc masr","mbc masr":"mbc masr",
    "mbc masr 2 hd":"mbc masr 2","mbc masr 2":"mbc masr 2",
    "abu dhabi sports 1":"ad sports 1","ad sports 1 hd":"ad sports 1",
    "abu dhabi sports 2":"ad sports 2","ad sports 2 hd":"ad sports 2",
    "dubai sports 1 hd":"dubai sports 1",
    "dubai sports 2 hd":"dubai sports 2",
    "ksa sports 1":"saudi sports 1",
    "ksasports 1":"saudi sports 1",
    "bbc arabic":"bbc arabic news",
    "cartoon network hd":"cartoon network arabic",
    "cn arabic":"cartoon network arabic",
    "cartoon network arabic 1":"cartoon network arabic",
    "space toon":"spacetoon",
}

def norm(s):
    s=PREFIX_RE.sub("",s or "")
    s=unicodedata.normalize("NFKC",s).casefold()
    s=s.replace("&"," and ")
    s=re.sub(r"\b(?:hd|sd|fhd|uhd|4k)\b"," ",s)
    s=re.sub(r"\b(?:tv|channel)\b"," ",s)
    s=re.sub(r"[._:/\\-]+"," ",s)
    s=re.sub(r"[^\w\u0600-\u06ff]+"," ",s)
    s=" ".join(s.split())
    return ALIASES.get(s,s)

def arabic_pct(s):
    if not s: return 0.0
    letters=[c for c in s if c.isalpha()]
    if not letters: return 0.0
    return 100*sum(1 for c in letters if AR.search(c))/len(letters)

def classify_language(name,id_):
    txt=(name+" "+id_).casefold()
    # Foreign/international channels should not be penalized for non-Arabic titles.
    if any(k in txt for k in ("english","cnn","bbc world","france 24 english","nhk","trt world","cgtn","dw ","zee","star plus","hgtv")):
        return "international"
    # Movie/series branded feeds: original/English title can be acceptable.
    if any(k in txt for k in ("movie","movies","series","action","thriller","persia","bollywood")):
        return "mixed"
    return "arabic"

def lang_score(r):
    cls=classify_language(r["name"],r["id"])
    name_ar=arabic_pct(r["name"])
    desc=float(r["desc_pct"])
    if cls=="arabic":
        # We do not have event-language % in this CSV, so reward Arabic channel
        # naming only mildly; description completeness remains decisive.
        return (8 if name_ar>30 else 0) + desc*0.25
    if cls=="mixed":
        return desc*0.30
    return desc*0.25

def provider_score(r):
    # OpenEPG slightly preferred when all else is equal; EPGShare remains fallback.
    return 8 if r["provider"]=="openepg" else 4

def rank(r):
    fp=min(int(float(r["future_programmes"])),300)
    fh=min(float(r["future_hours"]),168.0)
    desc=float(r["desc_pct"])
    score=fp*0.70 + fh*1.35 + desc*0.85 + lang_score(r) + provider_score(r)
    if LATAM_BAD.search(r["name"]+" "+r["id"]):
        score-=500
    return round(score,2)

def main():
    now=datetime.now(timezone.utc).isoformat()
    rows=list(csv.DictReader(ALL.open(encoding="utf-8")))
    rows=[r for r in rows if (r.get("provider",""),r.get("source","")) not in EXCLUDED_SOURCE_KEYS]
    for r in rows:
        r["future_programmes"]=int(float(r.get("future_programmes") or 0))
        r["future_hours"]=float(r.get("future_hours") or 0)
        r["desc_pct"]=float(r.get("desc_pct") or 0)
        r["canonical"]=norm(r["name"]) or norm(r["id"])
        r["rank_score"]=rank(r)

    # Dynamic zero-EPG blacklist: refreshed each run.
    zero=[r for r in rows if r["future_programmes"]<=0 or r["future_hours"]<=0]
    zero.sort(key=lambda x:(x["provider"],x["source"],x["name"].casefold()))
    zfields=["provider","source","id","name","future_programmes","future_hours","desc_pct","url"]
    with (OUT/"arab-fallback-zero-epg-blacklist.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=zfields+["reason"])
        w.writeheader()
        for r in zero:
            w.writerow({**{k:r.get(k,"") for k in zfields},"reason":"ZERO_FUTURE_EPG"})

    health=json.load(HEALTH.open(encoding="utf-8"))
    source_black=[]
    for h in health.get("health",[]):
        if h.get("status")!="ok":
            source_black.append({
                "provider":h["provider"],"source":h["source"],"reason":"INVALID_SOURCE_XML",
                "detail":h.get("error","")
            })
        elif int(h.get("active_channels",0))==0:
            source_black.append({
                "provider":h["provider"],"source":h["source"],"reason":"ZERO_ACTIVE_CHANNELS",
                "detail":f'{h.get("channels",0)} channels, 0 active'
            })
    with (OUT/"arab-fallback-source-blacklist.json").open("w",encoding="utf-8") as f:
        json.dump({"generated_at":now,"sources":source_black},f,ensure_ascii=False,indent=2)
        f.write("\n")

    # Only active rows enter duplicate arbitration.
    active=[r for r in rows if r not in zero]
    groups=defaultdict(list)
    for r in active:
        groups[r["canonical"]].append(r)

    decisions=[]
    for canonical,arr in groups.items():
        arr=sorted(arr,key=lambda x:(x["rank_score"],x["future_programmes"],x["desc_pct"],x["future_hours"]),reverse=True)
        winner=arr[0]
        decisions.append({
            "canonical":canonical,
            "winner_provider":winner["provider"],
            "winner_source":winner["source"],
            "winner_id":winner["id"],
            "winner_name":winner["name"],
            "future_programmes":winner["future_programmes"],
            "future_hours":winner["future_hours"],
            "desc_pct":winner["desc_pct"],
            "rank_score":winner["rank_score"],
            "alternatives_count":len(arr)-1,
            "alternatives":";".join(
                f'{x["provider"]}:{x["source"]}:{x["id"]}:{x["rank_score"]}'
                for x in arr[1:]
            ),
            "decision":"BLACKLIST_LATAM" if LATAM_BAD.search(winner["name"]+" "+winner["id"]) else (
                "UNIQUE" if len(arr)==1 else "WINNER_OF_DUPLICATES"
            )
        })
    decisions.sort(key=lambda x:(x["decision"]=="BLACKLIST_LATAM",-x["rank_score"]))

    dfields=["canonical","winner_provider","winner_source","winner_id","winner_name",
             "future_programmes","future_hours","desc_pct","rank_score",
             "alternatives_count","alternatives","decision"]
    with (OUT/"arab-fallback-duplicate-decisions.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=dfields); w.writeheader(); w.writerows(decisions)

    # New IDs list = current unmapped candidates after analysis, excluding obvious
    # LATAM pollution and excluding zero-EPG IDs.
    unmapped=list(csv.DictReader(UNMAPPED.open(encoding="utf-8")))
    new=[]
    zero_keys={(r["provider"],r["source"],r["id"]) for r in zero}
    for r in unmapped:
        if (r["provider"],r["source"],r["id"]) in zero_keys:
            continue
        if LATAM_BAD.search(r["name"]+" "+r["id"]):
            continue
        new.append(r)
    new.sort(key=lambda r:(r["country"],r["name"].casefold(),r["id"]))

    nfields=["country","name","id","provider","source","future_programmes","future_hours","desc_pct","sample_title","sample_desc","alternatives","alternative_sources","url"]
    with (OUT/"new-arab-epg-ids.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=nfields); w.writeheader()
        for r in new: w.writerow({k:r.get(k,"") for k in nfields})
    (OUT/"new-arab-epg-ids.txt").write_text(
        "\n".join(f'{r["id"]}\t{r["name"]}\t{r["provider"]}:{r["source"]}' for r in new)+"\n",
        encoding="utf-8"
    )

    counts=Counter(x["decision"] for x in decisions)
    summary={
        "generated_at":now,
        "active_rows":len(active),
        "zero_epg_blacklisted_ids":len(zero),
        "source_blacklist":source_black,
        "canonical_groups":len(groups),
        "duplicate_groups":sum(1 for a in groups.values() if len(a)>1),
        "duplicate_extra_rows":sum(max(0,len(a)-1) for a in groups.values()),
        "decision_counts":dict(counts),
        "new_ids_after_zero_and_latam_filter":len(new),
        "excluded_sources":["epgshare:AR1"],
        "integration_policy":{
            "healthy_direct_feed":"always_keep",
            "fallback":"only_for_receiver_or_catalogue_channels_with_zero_epg",
            "duplicate":"use winner; keep alternatives for failover",
            "zero_epg":"dynamic_blacklist_until_future_programmes_return",
            "source_zero_or_invalid":"source_blacklist"
        }
    }
    (OUT/"arab-fallback-final-analysis.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    lines=["# Arab fallback final analysis","",
           f'Active fallback rows: **{len(active)}**  ',
           f'Zero-EPG IDs blacklisted: **{len(zero)}**  ',
           f'Canonical groups: **{len(groups)}**  ',
           f'Duplicate groups: **{summary["duplicate_groups"]}**  ',
           f'Extra duplicate rows collapsed: **{summary["duplicate_extra_rows"]}**  ',
           f'New IDs after zero/LatAm filtering: **{len(new)}**',"",
           "## Source blacklist","",
           "| Provider | Source | Reason | Detail |","|---|---|---|---|"]
    for s in source_black:
        lines.append(f'| {s["provider"]} | {s["source"]} | {s["reason"]} | {s["detail"]} |')
    lines += ["","## Integration rule","",
              "Healthy direct sources are never replaced. Fallback winners are only candidates for channels that still have zero EPG. Duplicate alternatives remain available as failover; zero-programme IDs stay dynamically blacklisted until they recover future programmes."]
    (OUT/"arab-fallback-final-analysis.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

    print(json.dumps(summary,ensure_ascii=False))
    print("NEW_IDS",len(new))
    print("ZERO_BLACKLIST",len(zero))
    print("DUPLICATE_GROUPS",summary["duplicate_groups"])
    return 0

if __name__=="__main__":
    raise SystemExit(main())
