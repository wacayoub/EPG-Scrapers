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
import csv, gzip, json, re, unicodedata
import xml.etree.ElementTree as ET
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
    # Arabic <-> Latin canonical aliases for common MENA channels.
    "العربية":"al arabiya",
    "العربية business":"al arabiya business",
    "الحدث":"al hadath",
    "دبي":"dubai",
    "دبي وان":"dubai one",
    "دبي زمان":"dubai zaman",
    "سما دبي":"sama dubai",
    "الشارقة":"sharjah",
    "السعودية":"saudiya",
    "السعودية tv":"saudiya",
    "إس بي سي":"sbc",
    "ام بي سي":"mbc1",
    "إم بي سي":"mbc1",
    "ام بي سي 1":"mbc1",
    "إم بي سي 1":"mbc1",
    "ام بي سي 2":"mbc2",
    "إم بي سي 2":"mbc2",
    "ام بي سي 3":"mbc3",
    "إم بي سي 3":"mbc3",
    "ام بي سي 4":"mbc4",
    "إم بي سي 4":"mbc4",
    "ام بي سي 5":"mbc5",
    "إم بي سي 5":"mbc5",
    "إم بي سي أكشن":"mbc action",
    "إم بي سي ماكس":"mbc max",
    "إم بي سي بوليوود":"mbc bollywood",
    "إم بي سي العراق":"mbc iraq",
    "إم بي سي مصر":"mbc masr",
    "إم بي سي مصر 2":"mbc masr 2",
    "إم بي سي مصر دراما":"mbc masr drama",
    "روتانا سينما":"rotana cinema",
    "روتانا سينما مصر":"rotana cinema masr",
    "روتانا كلاسيك":"rotana classic",
    "روتانا كوميدي":"rotana comedy",
    "روتانا دراما":"rotana drama",
    "روتانا خليجية":"rotana khalijia",
    "الجديد":"al jadeed",
    "السومرية":"alsumaria",
    "الرشيد":"alrasheed",
    "الأردن":"jordan",
    "رؤيا":"roya",
    "الفجيرة":"fujairah",
    "الظفرة":"al dafrah",
    "الحياة":"alhayat",
    "القاهرة والناس":"al kahera wal nas",
    "القاهرة والناس 2":"al kahera wal nas 2",
    "النهار":"al nahar",
    "النهار دراما":"al nahar drama",
    "المحور":"mehwar",
    "أون إي":"on e",
    "أون دراما":"on drama",
    "دي إم سي":"dmc",
    "دي إم سي دراما":"dmc drama",
    "سي بي سي":"cbc",
    "سي بي سي دراما":"cbc drama",
    "صدى البلد":"sada el balad",
    "صدى البلد 2":"sada el balad 2",
    "صدى البلد دراما":"sada el balad drama",
    "نايل دراما":"nile drama",
    "نايل لايف":"nile life",
    "ميكس وان":"mix one",
    "زي ألوان":"zee alwan",
    "أو إس إن وان":"osn tv one",
    "أو إٍس إن ناو":"osn tv now",
    "أو إس إن كوميدي":"osn tv comedy",
    "أو إس إن كرايم":"osn tv crime",
    "أو إس إن شو كايس":"osn tv showcase",
    "أو إس إن ياهلا":"osn ya hala",
    "أو إس إن ياهلا بالعربي":"osn tv yahala bil arabi",
    "أو إس إن ياهلا أفلام":"osn ya hala aflam",
    "بي إن دراما":"bein drama",
    "بي إن موفيز أكشن":"bein movies action",
    "بي إن موفيز دراما":"bein movies drama",
    "بي إن موفيز فاميلي":"bein movies family",
    "بي إن موفيز بريمير":"bein movies premiere",
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

def language_rank(r):
    """Prefer Arabic variant, then neutral/original, then explicit English."""
    name=(r.get("name") or "").strip()
    cid=(r.get("id") or "").strip()
    txt=(name+" "+cid).casefold()
    ar_marker=re.search(r"(?:^|[_.\s-])ar(?:$|[_.\s-])",txt,re.I)
    en_marker=re.search(r"(?:^|[_.\s-])en(?:$|[_.\s-])",txt,re.I)
    if AR.search(name) or AR.search(cid) or ar_marker or re.match(r"^\s*arabic\b",name,re.I):
        return 0
    if en_marker or re.match(r"^\s*english\b",name,re.I) or " english" in txt:
        return 2
    return 1

def bilingual_key(r):
    """Collapse AR/EN variants even when language is in prefix or suffix."""
    name=(r.get("name") or "").strip()
    cid=(r.get("id") or "").strip()
    for raw in (name,cid):
        s=raw
        s=re.sub(r"\.(?:ae|sa|eg|qa|bein|net)$","",s,flags=re.I)
        s=re.sub(r"^\s*(?:ar|en|arabic|english)\s*[:._ -]*","",s,flags=re.I)
        s=re.sub(r"[:._ -]+(?:ar|en|arabic|english)\s*$","",s,flags=re.I)
        s=re.sub(r"(?i)(?:_DIGITAL_Mono)?_(?:AR|EN)$","",s)
        s=norm(s)
        if s:
            return s
    return norm(name) or norm(cid)

def load_direct_catalogue():
    """Return healthy published direct IDs and normalized channel names."""
    direct_ids=set()
    direct_names=defaultdict(list)
    now_dt=datetime.now(timezone.utc)
    for path in sorted(Path("feeds").glob("*.xml.gz")):
        try:
            data=path.read_bytes()
            if data[:2]==b"\x1f\x8b":
                data=gzip.decompress(data)
            root=ET.fromstring(data)
        except Exception:
            continue

        future_counts=Counter()
        for p in root.findall("programme"):
            raw=(p.get("stop") or "").strip()
            try:
                stop=datetime.strptime(raw[:14],"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if stop>now_dt:
                future_counts[(p.get("channel") or "").strip()] += 1

        for ch in root.findall("channel"):
            cid=(ch.get("id") or "").strip()
            if not cid or future_counts[cid] <= 0:
                continue
            names=[(x.text or "").strip() for x in ch.findall("display-name") if (x.text or "").strip()]
            if not names:
                names=[cid]
            direct_ids.add(cid)
            for name in names:
                key=norm(name)
                if key:
                    direct_names[key].append({"id":cid,"feed":path.name,"name":name})
            id_key=norm(cid)
            if id_key:
                direct_names[id_key].append({"id":cid,"feed":path.name,"name":names[0]})
    return direct_ids,direct_names

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

    direct_ids,direct_names=load_direct_catalogue()

    # New IDs list = current unmapped candidates after analysis, excluding obvious
    # LATAM pollution and excluding zero-EPG IDs.
    unmapped=list(csv.DictReader(UNMAPPED.open(encoding="utf-8")))
    raw_new=[]
    zero_keys={(r["provider"],r["source"],r["id"]) for r in zero}
    for r in unmapped:
        if (r["provider"],r["source"],r["id"]) in zero_keys:
            continue
        if (r.get("provider",""),r.get("source","")) in EXCLUDED_SOURCE_KEYS:
            continue
        if LATAM_BAD.search((r.get("name") or "")+" "+(r.get("id") or "")):
            continue
        raw_new.append(r)

    # Merge all fallback variants by real channel identity. Arabic wins over
    # neutral/original, and English is used only if no Arabic variant exists.
    lang_groups=defaultdict(list)
    for r in raw_new:
        lang_groups[bilingual_key(r)].append(r)

    merged=[]
    language_duplicates_removed=0
    for canonical,arr in lang_groups.items():
        arr=sorted(
            arr,
            key=lambda r:(
                language_rank(r),
                -int(float(r.get("future_programmes") or 0)),
                -float(r.get("desc_pct") or 0),
                -float(r.get("future_hours") or 0),
                -provider_score(r),
                (r.get("name") or "").casefold(),
                r.get("id") or ""
            )
        )
        winner=dict(arr[0])
        winner["merge_key"]=canonical
        winner["merged_alternatives"]=";".join(
            f'{x.get("provider","")}:{x.get("source","")}:{x.get("id","")}'
            for x in arr[1:]
        )
        merged.append(winner)
        language_duplicates_removed += max(0,len(arr)-1)

    # Remove anything already covered by a healthy priority/direct source.
    # Match exact XMLTV ID plus normalized/bilingual channel identity.
    new=[]
    already_covered=[]
    for r in merged:
        direct_matches=[]
        if (r.get("id") or "") in direct_ids:
            direct_matches.append({"id":r["id"],"feed":"exact-id","name":r.get("name","")})
        keys={norm(r.get("name") or ""),bilingual_key(r),norm(r.get("id") or "")}
        for key in keys:
            if key and key in direct_names:
                direct_matches.extend(direct_names[key])

        if direct_matches:
            seen=set()
            uniq=[]
            for m in direct_matches:
                k=(m["id"],m["feed"])
                if k in seen:
                    continue
                seen.add(k)
                uniq.append(m)
            rr=dict(r)
            rr["covered_by"]=";".join(f'{m["feed"]}:{m["id"]}' for m in uniq)
            already_covered.append(rr)
        else:
            new.append(r)

    # Final missing-ID list only: alphabetical by channel name.
    new.sort(key=lambda r:((r.get("name") or "").casefold(),(r.get("id") or "").casefold()))
    already_covered.sort(key=lambda r:((r.get("name") or "").casefold(),(r.get("id") or "").casefold()))

    nfields=["country","name","id","provider","source","future_programmes","future_hours","desc_pct","sample_title","sample_desc","alternatives","alternative_sources","merged_alternatives","url"]
    with (OUT/"new-arab-epg-ids.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=nfields); w.writeheader()
        for r in new: w.writerow({k:r.get(k,"") for k in nfields})
    (OUT/"new-arab-epg-ids.txt").write_text(
        "\n".join(f'{r["id"]}\t{r["name"]}\t{r["provider"]}:{r["source"]}' for r in new)+"\n",
        encoding="utf-8"
    )

    covered_fields=nfields+["covered_by"]
    with (OUT/"arab-fallback-already-covered.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=covered_fields); w.writeheader()
        for r in already_covered:
            w.writerow({k:r.get(k,"") for k in covered_fields})

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
        "merged_fallback_winners_before_direct_filter":len(merged),
        "already_covered_by_direct_sources":len(already_covered),
        "missing_ids_final":len(new),
        "new_ids_after_zero_and_latam_filter":len(new),
        "language_duplicates_removed":language_duplicates_removed,
        "language_policy":"ARABIC_FIRST_THEN_ENGLISH_IF_NO_ARABIC",
        "sort_order":"CHANNEL_NAME_ASC",
        "excluded_sources":["epgshare:AR1"],
        "integration_policy":{
            "healthy_direct_feed":"always_keep",
            "fallback":"only_missing_ids_not_covered_by_any_healthy_direct_source",
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
