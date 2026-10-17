#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find real, fresh OSN Legacy programme donors already in published feeds.

Zero source changes. Exact XMLTV ID matching by default. Explicit aliases
are supplied only for provider-confirmed Pinoy channel identities.
Do not use MENA aggregated guides as independent evidence (circular fallback).
Never log episode titles or copy provider content to a public report.
"""
from __future__ import annotations
import gzip
import hashlib
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import re
import xml.etree.ElementTree as ET

SOURCE_NAMES=("morocco","bein","osn","elcinema","starzplay","stctv",
              "shahid","dubaiplus","sport24","rotana","aljazeera",
              "alkass","tabie","tunisiatv")
ALIAS={
 "osn.213":("MORGlobalRadio.ph",),
 "osn.215":("DZMMTeleRadyo.ph",),
 "osn.216":("CinemaOne.ph",),
 "osn.217":("TheFilipinoChannelMiddleEast.us",),
 "osn.220":("KapatidTV5.ph",),
}
MAX_COMPRESSED=14_000_000
MAX_DECOMPRESSED=90_000_000
FMT=re.compile(r"^(\d{14})\s+([+-]\d{4}|Z)$")

def get_utc(s):
    m=FMT.fullmatch((s or "").strip())
    if not m:return None
    try:
        if m[2]=="Z":
            return datetime.strptime(m[1],"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return datetime.strptime(m[1]+" "+m[2],"%Y%m%d%H%M%S %z").astimezone(timezone.utc)
    except ValueError:
        return None

def safe_root(filepath):
    raw=filepath.read_bytes()
    if not 0<len(raw)<=MAX_COMPRESSED:raise ValueError("oversize or empty gzip")
    with gzip.GzipFile(fileobj=__import__("io").BytesIO(raw)) as reader:
        blob=reader.read(MAX_DECOMPRESSED+1)
    if len(blob)>MAX_DECOMPRESSED:raise ValueError("oversize unpacked XMLTV")
    root=ET.fromstring(blob)
    if root.tag!="tv":raise ValueError("not tv")
    return root

def published(name, repo, now):
    feed=Path(repo)/"feeds"/f"{name}.xml.gz"
    meta=Path(repo)/"feeds"/f"{name}.json"
    if feed.is_symlink() or not feed.is_file() or not meta.is_file():
        return None,"unavailable"
    try:
        j=json.loads(meta.read_text(encoding="utf8"))
        t=datetime.fromisoformat(j["generated_utc"].replace("Z","+00:00")).astimezone(timezone.utc)
        if t>now+timedelta(hours=1) or now-t>timedelta(hours=72):
            return None,"stale"
        bytesize=feed.stat().st_size
        if bytesize!=j["size_bytes"] or hashlib.sha256(feed.read_bytes()).hexdigest()!=j["sha256"]:
            return None,"sha_mismatch"
        return safe_root(feed),"verified_published"
    except (ValueError,KeyError,TypeError,IndexError,ET.ParseError,OSError):
        return None,"invalid_feed"

def missing_ids(repo):
    obj=json.loads((Path(repo)/"feeds"/"osn.json").read_text(encoding="utf8"))
    ids=obj.get("zero_epg_ids")
    if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):
        raise ValueError("missing OSN zero EPG published list")
    return sorted(set(ids))

def candidates(root, aliases, now):
    valid=set(aliases)
    count={x:0 for x in valid}
    # Reject any row without strictly qualified UTC start/stop and a real title.
    for p in root.findall("programme"):
        cid=p.get("channel")
        if cid not in valid:continue
        start=get_utc(p.get("start"))
        stop=get_utc(p.get("stop"))
        name=(p.findtext("title") or "").strip()
        if not start or not stop or not (now-timedelta(hours=2)<=stop<=now+timedelta(hours=72)):
            continue
        if not start<stop or stop-start>timedelta(hours=8) or not 2<len(name)<180:
            continue
        if name.casefold() in ("no information","programme unavailable","البرنامج غير متوفر"):
            continue
        count[cid]+=1
    return {x:n for x,n in count.items() if n}

def analyze(repo,now=None):
    now=now or datetime.now(timezone.utc)
    targets=missing_ids(repo)
    result={"audit":"OSN legacy exact-ID donor availability, no feed modifications",
            "checked_utc":now.isoformat(),"targets":len(targets),
            "receiver_modified":False,"feed_republished":False,
            "automatic_source_acceptance":False,
            "by_source":{},"donors_by_target":{x:[] for x in targets}}
    for source in SOURCE_NAMES:
        if source=="osn":continue
        root,state=published(source,repo,now)
        summary={"status":state,"targets_with_future_epg":0}
        if root is not None:
            for target in targets:
                ids=(target,)+ALIAS.get(target,())
                counts=candidates(root,ids,now)
                if counts:
                    summary["targets_with_future_epg"]+=1
                    result["donors_by_target"][target].append({
                        "source":source,"source_ids":counts,"stage":"MATCH_CANDIDATE_NOT_VERIFIED"
                    })
        result["by_source"][source]=summary
    result["targets_with_any_candidate"]=sum(bool(x) for x in result["donors_by_target"].values())
    return result

def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo",default=".")
    args=ap.parse_args()
    print(json.dumps(analyze(Path(args.repo)),ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
