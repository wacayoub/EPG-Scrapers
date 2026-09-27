#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Low-rate STC TV public metadata XMLTV source.

Purpose:
- STARZPLAY Sports 1/2/3: direct structured EPG fallback/source.
- MBC / Wanasah / Al Arabiya: fallback only when the primary Shahid feed has
  zero/placeholder EPG.

Uses only public guest metadata loaded by web.stctv.com. No playback, DRM,
account login or entitlement bypass. Requests are sequential and deliberately
rate-limited.
"""
from __future__ import annotations
import argparse, json, re, time, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
import requests

UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
APP_KEY="webB2CGDMPrdExy0sVDlZMzNDdUyZ"
SCHEDULE_KEY="GDMPrdExy0sVDlZMzNDdUyZ"
CHANNELS_API=f"https://jawwy2-prod-cdn.intigral-ott.net/bolt/v2/{APP_KEY}/channels"
SCHEDULE_BASE="https://prod-cdn-content-api.intigral-ott.net/content-api-3.0.1/channels/schedules"
TARGET=re.compile(r"(starz\s*play|mbc|wanasah|al\s*arabiya)",re.I)
AR=re.compile(r"[\u0600-\u06ff]")
NONWORD=re.compile(r"[^a-z0-9]+")

ALIASES={
 "starzplay sports 1":"StarzplaySports1.sa@HD",
 "starzplay sports 2":"StarzplaySports2.sa@HD",
 "starzplay sports 3":"StarzplaySports3.sa@HD",
 "mbc":"MBC1.sa@HD",
 "mbc 2":"MBC2.sa@HD",
 "mbc 3":"MBC3.sa@HD",
 "mbc 4":"MBC4.sa@HD",
 "mbc action":"MBCAction.sa@HD",
 "mbc max":"MBCMax.sa@HD",
 "mbc bollywood":"MBCBollywood.sa@HD",
 "mbc drama":"MBCDrama.sa@HD",
 "mbc masr":"MBCMasr.eg@HD",
 "mbc masr 2":"MBCMasr2.eg@HD",
 "wanasah":"Wanasah.ae@SD",
 "al arabiya":"AlArabiya.sa@HD",
}
HYBRID_TOKENS=("starzplay sports","mbc 2","mbc max","mbc 4","mbc action","mbc bollywood","mbc variety")

def norm(s):
    return " ".join(NONWORD.sub(" ",(s or "").casefold()).split())

def read_index(path):
    out={}
    p=Path(path) if path else None
    if not p or not p.exists(): return out
    for line in p.read_text(encoding="utf-8",errors="ignore").splitlines():
        if "|" not in line: continue
        cid,name=line.split("|",1)
        if cid.strip() and name.strip():
            out.setdefault(norm(name),cid.strip())
    return out

def xml_id(name,index):
    n=norm(name)
    if n in index: return index[n]
    if n in ALIASES: return ALIASES[n]
    for k,v in ALIASES.items():
        if n==k or n.startswith(k+" "): return v
    return "stctv."+hashlib.sha1(n.encode()).hexdigest()[:12]

def get_json(s,url,params,timeout):
    r=s.get(url,params=params,timeout=timeout)
    r.raise_for_status()
    return r.json()

def get_channels(data):
    d=data.get("data") if isinstance(data,dict) else None
    return d.get("channels",[]) if isinstance(d,dict) and isinstance(d.get("channels"),list) else []

def rows(data):
    out=[]
    if isinstance(data,list):
        for b in data:
            if isinstance(b,dict) and isinstance(b.get("listings"),list):
                out.extend(b["listings"])
    return out

def fmt(ms):
    return datetime.fromtimestamp(ms/1000,tz=timezone.utc).strftime("%Y%m%d%H%M%S +0000")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",required=True)
    ap.add_argument("--report",required=True)
    ap.add_argument("--id-index",default="feeds/mena.txt")
    ap.add_argument("--window-hours",type=int,default=48)
    ap.add_argument("--delay",type=float,default=1.5)
    ap.add_argument("--timeout",type=int,default=20)
    ap.add_argument("--max-channels",type=int,default=30)
    args=ap.parse_args()

    now=datetime.now(timezone.utc); end=now+timedelta(hours=max(1,args.window_hours))
    days=[]
    d=now.date()
    while datetime.combine(d,datetime.min.time(),tzinfo=timezone.utc) < end+timedelta(days=1):
        days.append(d.isoformat()); d+=timedelta(days=1)
    index=read_index(args.id_index)
    sess=requests.Session()
    sess.headers.update({"User-Agent":UA,"Accept":"application/json,text/plain,*/*",
        "Accept-Language":"ar-SA,ar;q=0.9,en;q=0.7","Origin":"https://web.stctv.com",
        "Referer":"https://web.stctv.com/"})
    root=ET.Element("tv",{"generator-info-name":"EPGManager STC TV public low-rate",
        "generator-info-url":"https://web.stctv.com/"})
    stats={"generated_utc":now.isoformat(),"channels":0,"programmes":0,"requests":0,
           "target_channels":0,"zero_epg":[],"hybrid_channels":[],"samples":{}}
    try:
        data=get_json(sess,CHANNELS_API,{"country":"SA","deviceType":"web","filter":"","device":"PC","appKey":APP_KEY},args.timeout)
        stats["requests"]+=1
        targets=[]
        for ch in get_channels(data):
            en=str(ch.get("channelTitle") or "")
            ar=str(ch.get("channelTitleAr") or "")
            if TARGET.search(en) or TARGET.search(ar):
                targets.append(ch)
        targets=targets[:args.max_channels]
        stats["target_channels"]=len(targets)
        for ci,ch in enumerate(targets):
            name=str(ch.get("channelTitle") or ch.get("channelTitleAr") or "").strip()
            sid=str(ch.get("channelID") or "")
            cid=xml_id(name,index)
            prof="hybrid" if any(tok in norm(name) for tok in HYBRID_TOKENS) else "arabic_native"
            if prof=="hybrid": stats["hybrid_channels"].append(cid)
            allrows=[]
            for di,date in enumerate(days):
                try:
                    data2=get_json(sess,f"{SCHEDULE_BASE}/{date}/3",
                        {"apikey":SCHEDULE_KEY,"productKey":"stc-tv","byId":sid},args.timeout)
                    stats["requests"]+=1
                    allrows.extend(rows(data2))
                except Exception:
                    pass
                if di+1<len(days): time.sleep(max(0,args.delay))
            seen=set(); keep=[]
            for li in allrows:
                st=int(li.get("startTime") or 0); et=int(li.get("endTime") or 0)
                if not st or not et: continue
                sdt=datetime.fromtimestamp(st/1000,tz=timezone.utc)
                edt=datetime.fromtimestamp(et/1000,tz=timezone.utc)
                if sdt>=end or edt<=now-timedelta(hours=1): continue
                key=(st,et,str(li.get("listingId") or li.get("title") or ""))
                if key in seen: continue
                seen.add(key); keep.append(li)
            if keep:
                c=ET.SubElement(root,"channel",{"id":cid})
                ET.SubElement(c,"display-name",{"lang":"en"}).text=name
                if str(ch.get("channelTitleAr") or "").strip():
                    ET.SubElement(c,"display-name",{"lang":"ar"}).text=str(ch.get("channelTitleAr")).strip()
                ET.SubElement(c,"url",{"system":"stctv-id"}).text=sid
                stats["channels"]+=1
                for li in sorted(keep,key=lambda x:int(x.get("startTime") or 0)):
                    lt=li.get("localizedTitle") or {}; ld=li.get("localizedDescription") or {}
                    en_title=str(li.get("title") or "").strip()
                    ar_title=str(lt.get("ar") or "").strip() if isinstance(lt,dict) else ""
                    ar_desc=str(ld.get("ar") or "").strip() if isinstance(ld,dict) else ""
                    if prof=="hybrid":
                        title=en_title or ar_title; lang="en" if en_title else "ar"
                    else:
                        title=ar_title or en_title; lang="ar" if ar_title else "en"
                    if not title: continue
                    p=ET.SubElement(root,"programme",{"channel":cid,
                        "start":fmt(int(li["startTime"])),"stop":fmt(int(li["endTime"]))})
                    ET.SubElement(p,"title",{"lang":lang}).text=title
                    if ar_desc:
                        ET.SubElement(p,"desc",{"lang":"ar"}).text=ar_desc
                    stats["programmes"]+=1
                    if cid not in stats["samples"]:
                        stats["samples"][cid]={"name":name,"profile":prof,"title":title,"desc":ar_desc[:220]}
            else:
                stats["zero_epg"].append({"id":cid,"name":name})
            if ci+1<len(targets): time.sleep(max(0,args.delay))
    except Exception as e:
        stats["error"]=str(e)

    ET.indent(root,space="  ")
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_bytes(ET.tostring(root,encoding="utf-8",xml_declaration=True))
    Path(args.report).parent.mkdir(parents=True,exist_ok=True)
    Path(args.report).write_text(json.dumps(stats,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in stats.items() if k!="samples"},ensure_ascii=False))
    return 0 if stats["channels"] and stats["programmes"] else 11

if __name__=="__main__":
    raise SystemExit(main())
