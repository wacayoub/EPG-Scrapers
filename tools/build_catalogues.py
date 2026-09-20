#!/usr/bin/env python3
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path("vendor/iptv-org-epg/sites")
OUT = Path("output/source-build")
OUT.mkdir(parents=True, exist_ok=True)

def choose(key, sites, arabic_only=False):
    rows=[]
    for site_rank, site in enumerate(sites):
        base=ROOT/site
        files=sorted(base.glob("*.channels.xml"))
        if arabic_only:
            preferred=base/f"{site}_ar.channels.xml"
            if preferred.exists():
                files=[preferred]
        for p in files:
            try:
                rr=ET.parse(p).getroot()
            except Exception:
                continue
            for c in rr.findall("channel"):
                cid=(c.get("xmltv_id") or "").strip()
                sid=(c.get("site_id") or "").strip()
                if not cid or not sid:
                    continue
                lang=(c.get("lang") or "").lower()
                lang_rank=0 if lang.startswith("ar") else (1 if lang.startswith("en") else 2)
                rows.append((cid,site_rank,lang_rank,p.name,c))
    best={}
    for cid,srank,lrank,name,c in rows:
        rank=(srank,lrank,name)
        if cid not in best or rank < best[cid][0]:
            best[cid]=(rank,c)
    root=ET.Element("channels")
    for cid in sorted(best,key=str.casefold):
        root.append(ET.fromstring(ET.tostring(best[cid][1],encoding="utf-8")))
    ET.indent(root,space="  ")
    path=OUT/f"{key}.channels.xml"
    path.write_bytes(ET.tostring(root,encoding="utf-8",xml_declaration=True))
    print(f"{key}: {len(root)} channels")
    if len(root)==0:
        raise SystemExit(f"{key}: empty catalogue")

choose("elcinema",["elcinema.com"],arabic_only=True)

def build_elcinema_fallback():
    base=ROOT/"elcinema.com"
    ar_file=base/"elcinema.com_ar.channels.xml"
    en_file=base/"elcinema.com_en.channels.xml"
    ar_root=ET.parse(ar_file).getroot()
    en_root=ET.parse(en_file).getroot()
    en_by_id={(c.get("xmltv_id") or "").strip():c for c in en_root.findall("channel")
              if (c.get("xmltv_id") or "").strip() and (c.get("site_id") or "").strip()}
    root=ET.Element("channels")
    recovered=0
    for ar in ar_root.findall("channel"):
        cid=(ar.get("xmltv_id") or "").strip()
        sid=(ar.get("site_id") or "").strip()
        if not cid or not sid:
            continue
        node=en_by_id.get(cid)
        if node is not None:
            root.append(ET.fromstring(ET.tostring(node,encoding="utf-8")))
            recovered+=1
        else:
            root.append(ET.fromstring(ET.tostring(ar,encoding="utf-8")))
    ET.indent(root,space="  ")
    path=OUT/"elcinema_fallback.channels.xml"
    path.write_bytes(ET.tostring(root,encoding="utf-8",xml_declaration=True))
    print(f"elcinema fallback: {len(root)} channels ({recovered} English alternates)")

build_elcinema_fallback()
choose("osn",["osn.com"])
choose("bein",["bein.com","beinsports.com"])
