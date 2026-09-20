#!/usr/bin/env python3
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path("vendor/iptv-org-epg/sites")
OUT = Path("output/source-build")

# Explicit production exclusions confirmed by manual EPG comparison.
ELCINEMA_PRODUCTION_EXCLUDE = {
    "AlAoula.ma@MiddleEast",
}
# Rotana mappings from ElCinema are quarantined until the official Rotana
# channel mapping is revalidated against the live/current programme.
def elcinema_excluded(cid: str) -> bool:
    return cid in ELCINEMA_PRODUCTION_EXCLUDE or cid.casefold().startswith("rotana")
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
                if key=="elcinema" and elcinema_excluded(cid):
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
        if elcinema_excluded(cid):
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

BEIN_ZERO_EPG_EXCLUDE = {
    "AlkassEight.qa@SD",
    "beINSportsNBA.qa@SD",
}

def build_bein():
    rows=[]
    mena_en_by_site={}
    mena_en=ROOT/"beinsports.com"/"beinsports.com_mena-en.channels.xml"
    if mena_en.exists():
        try:
            rr=ET.parse(mena_en).getroot()
            for ch in rr.findall("channel"):
                sid=(ch.get("site_id") or "").strip()
                cid=(ch.get("xmltv_id") or "").strip()
                if sid and cid:
                    mena_en_by_site[sid]=cid
        except Exception:
            pass
    for site in ["beinsports.com","bein.com"]:
        base=ROOT/site
        files=sorted(base.glob("*.channels.xml"))
        if site=="beinsports.com":
            files=[p for p in files if "_mena-ar.channels.xml" in p.name.lower()]
        elif site=="bein.com":
            files=[p for p in files if p.name.lower().endswith("_ar.channels.xml")]
        for p in files:
            try:
                rr=ET.parse(p).getroot()
            except Exception:
                continue
            for ch in rr.findall("channel"):
                cid=(ch.get("xmltv_id") or "").strip()
                sid=(ch.get("site_id") or "").strip()
                if site=="beinsports.com" and sid and not cid:
                    cid=mena_en_by_site.get(sid,"")
                    if cid:
                        ch=ET.fromstring(ET.tostring(ch,encoding="utf-8"))
                        ch.set("xmltv_id",cid)
                if not cid or not sid:
                    continue
                # AFC temporary/event channels are no longer valid for the
                # production beIN MENA feed.
                if "afc" in cid.lower() or "afc" in (ch.text or "").lower():
                    continue
                if cid in BEIN_ZERO_EPG_EXCLUDE:
                    continue
                lang=(ch.get("lang") or "").lower()
                name=p.name.lower()
                # MENA sports API is preferred because its parser includes full
                # event descriptions. The legacy bein.com HTML adapter is kept
                # for entertainment and any IDs missing from the sports API.
                if site=="beinsports.com" and "mena-ar" in name:
                    rank=0
                elif site=="bein.com" and lang.startswith("ar"):
                    rank=1
                else:
                    rank=2
                rows.append((cid,rank,name,ch))
    best={}
    for cid,rank,name,ch in rows:
        key=(rank,name)
        if cid not in best or key < best[cid][0]:
            best[cid]=(key,ch)
    root=ET.Element("channels")
    for cid in sorted(best,key=str.casefold):
        root.append(ET.fromstring(ET.tostring(best[cid][1],encoding="utf-8")))
    ET.indent(root,space="  ")
    path=OUT/"bein.channels.xml"
    path.write_bytes(ET.tostring(root,encoding="utf-8",xml_declaration=True))
    print(f"bein: {len(root)} channels (MENA sports API preferred for descriptions)")
    if len(root)==0:
        raise SystemExit("bein: empty catalogue")

build_bein()
