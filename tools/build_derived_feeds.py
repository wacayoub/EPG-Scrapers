#!/usr/bin/env python3
from __future__ import annotations
import gzip, hashlib, json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

FEEDS=Path("feeds")
PRIORITY=["morocco","bein","shahid","rotana","sport24","osn","elcinema"]
EXTRA_MBC_GROUP_IDS={
    "AlarabiyaPortrait.ae@SD",
    "Alarabiya.ae@SD",
    "AlHadath.sa@SD",
}

def read_root(path: Path):
    raw=path.read_bytes()
    if path.suffix==".gz" or raw[:2]==b"\x1f\x8b":
        raw=gzip.decompress(raw)
    return ET.fromstring(raw)

def clone(node):
    return ET.fromstring(ET.tostring(node,encoding="utf-8"))

def write_feed(name,channels,programmes,meta):
    root=ET.Element("tv",{
        "generator-info-name":meta.get("generator","EPG-Scrapers derived feed"),
        "generator-info-url":"https://github.com/wacayoub/EPG-Scrapers",
    })
    for cid in sorted(channels,key=str.casefold):
        root.append(clone(channels[cid]))
    count=0
    for cid in sorted(programmes,key=str.casefold):
        seen=set()
        for p in sorted(programmes[cid],key=lambda e:((e.get("start") or ""),(e.get("stop") or ""))):
            title="|".join((t.text or "").strip() for t in p.findall("title"))
            key=(p.get("start") or "",p.get("stop") or "",title)
            if key in seen:
                continue
            seen.add(key)
            root.append(clone(p))
            count+=1
    ET.indent(root,space="  ")
    xml=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    gz=gzip.compress(xml,compresslevel=9,mtime=0)
    (FEEDS/f"{name}.xml.gz").write_bytes(gz)
    lines=[]
    for cid in sorted(channels,key=str.casefold):
        display=next(((d.text or "").strip() for d in channels[cid].findall("display-name") if (d.text or "").strip()),cid)
        lines.append(f"{cid}|{display}")
    (FEEDS/f"{name}.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    out={
        "label":name,
        "channels":len(channels),
        "programmes":count,
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "sha256":hashlib.sha256(gz).hexdigest(),
        **meta,
    }
    (FEEDS/f"{name}.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(name,len(channels),count)

def source_data(name):
    path=FEEDS/f"{name}.xml.gz"
    if not path.exists():
        return {},defaultdict(list)
    root=read_root(path)
    channels={}
    programmes=defaultdict(list)
    for c in root.findall("channel"):
        cid=(c.get("id") or "").strip()
        if cid:
            channels[cid]=c
    for p in root.findall("programme"):
        cid=(p.get("channel") or "").strip()
        if cid in channels:
            programmes[cid].append(p)
    return channels,programmes

def is_mbc(cid):
    return cid.casefold().startswith("mbc") or cid in EXTRA_MBC_GROUP_IDS

# Shahid/MBC catalogue. Shahid is the channel identity authority. Until Shahid
# exposes a stable public multi-day guide endpoint, published OSN/ElCinema data
# supplies EPG for the same canonical MBC IDs. No programme is invented.
sh_channels={}
sh_programmes=defaultdict(list)
origin={}
for src in ["osn","elcinema"]:
    channels,programmes=source_data(src)
    for cid,node in channels.items():
        if not is_mbc(cid) or cid in sh_channels:
            continue
        sh_channels[cid]=node
        sh_programmes[cid]=programmes.get(cid,[])
        origin[cid]=src
if sh_channels:
    write_feed("shahid",sh_channels,sh_programmes,{
        "generator":"Shahid MBC catalogue / validated OSN-ElCinema EPG",
        "catalogue_url":"https://shahid.mbc.net/ar/livestream",
        "epg_origin":"published OSN/ElCinema fallback; no invented programmes",
        "channel_origin":origin,
    })

# Canonical union used when the receiver wants maximum coverage with one owner
# per XMLTV ID. Raw source feeds remain available separately.
sources={name:source_data(name) for name in PRIORITY if (FEEDS/f"{name}.xml.gz").exists()}
merged_channels={}
merged_programmes=defaultdict(list)
owners={}
for src in PRIORITY:
    if src not in sources:
        continue
    channels,programmes=sources[src]
    for cid,node in channels.items():
        if cid in merged_channels:
            continue
        merged_channels[cid]=node
        merged_programmes[cid]=programmes.get(cid,[])
        owners[cid]=src
if merged_channels:
    write_feed("mena",merged_channels,merged_programmes,{
        "generator":"EPG-Scrapers canonical MENA merged feed",
        "priority":PRIORITY,
        "owners":owners,
    })
