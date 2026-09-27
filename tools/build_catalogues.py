#!/usr/bin/env python3
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path("vendor/iptv-org-epg/sites")
OUT = Path("output/source-build")

# Explicit production exclusions confirmed by manual EPG comparison.
# Keep the full provider catalogue. Source preference is decided later in
# EPGManager/merged feeds; catalogue construction must not delete valid IDs.
ELCINEMA_PRODUCTION_EXCLUDE = set()

def elcinema_excluded(cid: str) -> bool:
    return cid in ELCINEMA_PRODUCTION_EXCLUDE

SHAHID_MBC_EXTRA = {
    "Alarabiya.ae@SD",
    "AlArabiyaBusiness.ae@SD",
    "AlArabiyaEnglish.sa@SD",
    "AlArabiyaPrograms.ae",
    "AlHadath.sa@SD",
    "Wanasah.ae@SD",
}

# OSN's official API currently exposes several active OSN-branded services
# without an iptv-org xmltv_id.  They were therefore silently discarded by
# choose(), even though the schedule API has real listings for them.  Keep
# stable EPGManager-local XMLTV IDs keyed by OSN's official site_id.
OSN_OFFICIAL_ID_OVERRIDES = {
    "204": "OSNOne.ae@SD",
    "208": "OSNShowcaseClassics.ae@SD",
    "221": "OSNIQIYI.ae@SD",
    "225": "OSNMoviesHorror.ae@SD",
    "226": "OSNPopUp2.ae@SD",
    "307": "OSNCrime.ae@SD",
    "314": "OSNDocumentary.ae@SD",
    "4502": "OSNNow.ae@SD",
    "5666": "OSNMoviesFamily.ae@SD",
    "5669": "OSNMoviesComedy.ae@SD",
    "5672": "OSNPopUp.ae@SD",
    "206": "OSNBlippiAndFriends",
    "1101": "OSNKTVChannel1HD",
    "6607": "OSNeClutchAccess",
    "6609": "OSNEsport24",
    "6610": "OSNeClutchLIVE",
    "6611": "OSNPadelTV",
    "6612": "OSNeClutchLIVE2",
    "6613": "OSNeClutchArabic",
    "9957": "OSNSTV1HD",
}

def shahid_mbc_allowed(cid: str) -> bool:
    # Full-source mode: retain every valid XMLTV ID exposed by Shahid.
    return bool(cid)

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
                if key=="osn" and not cid and sid in OSN_OFFICIAL_ID_OVERRIDES:
                    c=ET.fromstring(ET.tostring(c,encoding="utf-8"))
                    cid=OSN_OFFICIAL_ID_OVERRIDES[sid]
                    c.set("xmltv_id",cid)
                if not cid or not sid:
                    continue
                if key=="elcinema" and elcinema_excluded(cid):
                    continue
                if key=="shahid" and not shahid_mbc_allowed(cid):
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

def build_osn_english():
    base=ROOT/"osn.com"
    path=base/"osn.com_en.channels.xml"
    rr=ET.parse(path).getroot()
    rows=[]
    for c in rr.findall("channel"):
        cid=(c.get("xmltv_id") or "").strip()
        sid=(c.get("site_id") or "").strip()
        if not cid and sid in OSN_OFFICIAL_ID_OVERRIDES:
            c=ET.fromstring(ET.tostring(c,encoding="utf-8"))
            cid=OSN_OFFICIAL_ID_OVERRIDES[sid]
            c.set("xmltv_id",cid)
        if not cid or not sid:
            continue
        rows.append((cid,c))
    root=ET.Element("channels")
    for cid,c in sorted(rows,key=lambda x:x[0].casefold()):
        root.append(ET.fromstring(ET.tostring(c,encoding="utf-8")))
    ET.indent(root,space="  ")
    out=OUT/"osn_en.channels.xml"
    out.write_bytes(ET.tostring(root,encoding="utf-8",xml_declaration=True))
    print(f"osn English: {len(root)} channels")
    if len(root)==0:
        raise SystemExit("osn English: empty catalogue")

build_osn_english()
choose("shahid",["shahid.mbc.net"],arabic_only=True)
choose("rotana",["rotana.net"],arabic_only=True)

# Full-source mode: keep the complete MENA catalogue, including zero-EPG
# services and entries that upstream has not assigned an xmltv_id yet.
BEIN_ZERO_EPG_EXCLUDE = set()

def _bein_norm_name(value: str) -> str:
    raw="".join(ch.lower() for ch in (value or "") if ch.isalnum())
    # The two official MENA endpoints use both "SPORTS EN 1" and
    # "SPORTS1EN" (same service). Canonicalize token order before dedupe.
    m=re.fullmatch(r"beinsports(\\d+)(en|fr)",raw)
    if m:
        return f"beinsports{m.group(2)}{m.group(1)}"
    m=re.fullmatch(r"beinsports(en|fr)(\\d+)",raw)
    if m:
        return f"beinsports{m.group(1)}{m.group(2)}"
    return raw

def _bein_generated_id(site: str, sid: str, name: str) -> str:
    # Prefer a semantic ID so the same MENA service discovered through the
    # sports API and the legacy beIN guide converges to one stable ID.
    slug = _bein_norm_name(name)
    if slug and not slug.isdigit():
        return f"beINMENA.{slug}"
    safe_sid = "".join(ch for ch in sid if ch.isalnum())
    prefix = "sports" if site == "beinsports.com" else "guide"
    return f"beINMENA.{prefix}.{safe_sid}"

def build_bein():
    rows=[]
    source_counts={"beinsports_mena_ar":0,"bein_ar":0}
    generated_ids=set()

    # English mirrors are used only to recover missing canonical XMLTV IDs.
    fallback_by_site={}
    for p in [
        ROOT/"beinsports.com"/"beinsports.com_mena-en.channels.xml",
        ROOT/"bein.com"/"bein.com_en.channels.xml",
    ]:
        if not p.exists():
            continue
        try:
            rr=ET.parse(p).getroot()
        except Exception:
            continue
        for ch in rr.findall("channel"):
            sid=(ch.get("site_id") or "").strip()
            cid=(ch.get("xmltv_id") or "").strip()
            if sid and cid:
                fallback_by_site[(ch.get("site") or p.parent.name,sid)]=cid

    # First pass: collect every canonical name->ID mapping already known in
    # either Arabic MENA catalogue. This lets missing IDs reuse a canonical ID
    # instead of creating a duplicate service.
    known_name_to_id={}
    selected_files=[
        ("beinsports.com",ROOT/"beinsports.com"/"beinsports.com_mena-ar.channels.xml",0),
        ("bein.com",ROOT/"bein.com"/"bein.com_ar.channels.xml",1),
    ]
    parsed=[]
    for site,p,rank in selected_files:
        if not p.exists():
            continue
        try:
            rr=ET.parse(p).getroot()
        except Exception:
            continue
        source_counts["beinsports_mena_ar" if site=="beinsports.com" else "bein_ar"]=len(rr.findall("channel"))
        for ch in rr.findall("channel"):
            sid=(ch.get("site_id") or "").strip()
            if not sid:
                continue
            cid=(ch.get("xmltv_id") or "").strip()
            name=(ch.text or "").strip()
            if not cid:
                cid=fallback_by_site.get((site,sid),"")
            if cid and name:
                known_name_to_id.setdefault(_bein_norm_name(name),cid)
            parsed.append((site,rank,p.name,ch,sid,cid,name))

    for site,rank,filename,ch,sid,cid,name in parsed:
        node=ET.fromstring(ET.tostring(ch,encoding="utf-8"))
        if not cid:
            cid=known_name_to_id.get(_bein_norm_name(name),"")
        if not cid:
            cid=_bein_generated_id(site,sid,name)
            generated_ids.add(cid)
        node.set("xmltv_id",cid)
        if cid in BEIN_ZERO_EPG_EXCLUDE:
            continue
        # beinsports.com MENA is preferred for sports because it exposes
        # descriptions and explicit MENA channel IDs. bein.com Arabic retains
        # entertainment, kids, factual and any extra sports services.
        rows.append((cid,rank,filename,node))

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

    # Small machine-readable audit used by the one-hour MENA test workflow.
    import json
    audit={
        "scope":"MENA only",
        "source_entries":source_counts,
        "catalogue_ids":len(root),
        "generated_local_ids":len(generated_ids),
        "generated_ids":sorted(generated_ids,key=str.casefold),
        "zero_epg_policy":"retain",
    }
    (OUT/"bein-catalogue.json").write_text(
        json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    print(
        f"bein MENA: {len(root)} IDs "
        f"(sports source={source_counts['beinsports_mena_ar']}, "
        f"bein Arabic source={source_counts['bein_ar']}, "
        f"generated={len(generated_ids)})"
    )
    if len(root)==0:
        raise SystemExit("bein MENA: empty catalogue")

build_bein()


def build_bein_hybrid_english():
    """English catalogue for beIN entertainment channels used by Hybrid mode."""
    wanted={
        "beINGourmet.qa@SD",
        "beINMovies1Premiere.qa@SD",
        "beINMovies2Action.qa@SD",
        "beINMovies3Drama.qa@SD",
        "beINMovies4Family.qa@SD",
        "beINSeries1.qa@SD",
    }
    site_id_overrides={
        "entertainment#9": "beINSeries1.qa@SD",
        "entertainment#12": "beINGourmet.qa@SD",
    }
    src=ROOT/"bein.com"/"bein.com_en.channels.xml"
    rr=ET.parse(src).getroot()
    rows=[]
    for ch in rr.findall("channel"):
        sid=(ch.get("site_id") or "").strip()
        cid=(ch.get("xmltv_id") or "").strip()
        if not cid and sid in site_id_overrides:
            ch=ET.fromstring(ET.tostring(ch,encoding="utf-8"))
            cid=site_id_overrides[sid]
            ch.set("xmltv_id",cid)
        if cid in wanted and sid:
            rows.append((cid,ch))
    root=ET.Element("channels")
    for cid,ch in sorted(rows,key=lambda x:x[0].casefold()):
        root.append(ET.fromstring(ET.tostring(ch,encoding="utf-8")))
    ET.indent(root,space="  ")
    path=OUT/"bein_hybrid_en.channels.xml"
    path.write_bytes(ET.tostring(root,encoding="utf-8",xml_declaration=True))
    found={cid for cid,_ in rows}
    missing=sorted(wanted-found)
    print(f"bein hybrid English: {len(root)} channels; missing={missing}")
    if missing:
        raise SystemExit(f"bein hybrid English missing IDs: {missing}")

build_bein_hybrid_english()
