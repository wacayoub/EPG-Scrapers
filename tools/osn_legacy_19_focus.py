#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OSN Other/Legacy: focused 19 missing-guide IDs, never publish or map.

Build a small grabber catalogue from exact official provider GUIDs reported by
the Legacy provider. Inspect resulting XMLTV as COUNTS only, avoiding
copyrighted programme content and protecting 82 already functioning channels.

This is diagnostic, not a provider data-reuse authorization.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import xml.etree.ElementTree as ET

# Explicit verified ID -> OSN Legacy GUID mapping, from public catalogue probe.
FOCUS = {
    "AlfaSeries.ae@SD": "4514",
    "AlfaSeriesPlus2.ae@SD": "4513",
    "AlSafwa.ae@SD": "5674",
    "AlYawm.ae@SD": "5673",
    "Cinema1.ae@SD": "5675",
    "Cinema2.ae@SD": "5676",
    "Fann.ae@SD": "311",
    "MusicNow.ae@SD": "312",
    "ANC.ph": "224",
    "CineMo.ph": "223",
    "GMALifeTV.ph": "211",
    "GMANewsTV.ph": "203",
    "GMAPinoyTVMiddleEast.ph": "202",
    "MyxMiddleEast.ph": "209",
    "osn.216": "216",
    "osn.217": "217",
    "osn.220": "220",
    "osn.213": "213",
    "osn.215": "215",
}
ALFA = frozenset((
    "AlfaSeries.ae@SD", "AlfaSeriesPlus2.ae@SD", "AlSafwa.ae@SD",
    "AlYawm.ae@SD", "Cinema1.ae@SD", "Cinema2.ae@SD",
    "Fann.ae@SD", "MusicNow.ae@SD",
))
RADIO = frozenset(("osn.213", "osn.215"))
PINOY = frozenset(FOCUS) - ALFA - RADIO

def group(cid):
    return "alfa" if cid in ALFA else ("radio" if cid in RADIO else "pinoy")

def load_json(path):
    out = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(out, dict):
        raise ValueError("not a JSON object")
    return out

def catalogue(legacy_probe, published_meta):
    if len(FOCUS)!=19 or len(set(FOCUS.values()))!=19:
        raise ValueError("focus catalogue duplicates")
    actual_zero = set(published_meta.get("zero_epg_ids", ()))
    if not set(FOCUS).issubset(actual_zero):
        raise ValueError("published OSN zero-guide catalogue changed: re-review 19 IDs")
    items = legacy_probe["platforms"]["legacy"]["ar"]["items"]
    by_guid = {}
    for it in items:
        sid = str(it.get("site_id") or "").strip()
        if sid in by_guid:
            raise ValueError("duplicated provider GUID")
        by_guid[sid] = it
    root = ET.Element("channels")
    for cid, sid in sorted(FOCUS.items()):
        item = by_guid.get(sid)
        if not item:
            raise ValueError("provider GUID missing for " + cid)
        name = (item.get("name") or "").strip()
        if not name:
            raise ValueError("provider title missing for " + cid)
        node = ET.SubElement(root,"channel",{
            "site": "osn.com", "site_id": sid,
            "xmltv_id": cid, "lang": "ar",
        })
        node.text = name
    return root

def parse_xmltv_time(raw):
    if not raw or not isinstance(raw,str):
        return None
    for fmt in ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M %z"):
        try:
            return datetime.strptime(raw,fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    return None

def inspect(root, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone-aware now required")
    now = now.astimezone(timezone.utc)
    if root.tag != "tv":
        raise ValueError("wrong XMLTV root")
    count={cid:0 for cid in FOCUS}
    invalid=0
    unexpected=set()
    for row in root.findall("programme"):
        cid=row.get("channel") or ""
        if cid not in FOCUS:
            unexpected.add(cid)
            continue
        begin = parse_xmltv_time(row.get("start"))
        end = parse_xmltv_time(row.get("stop"))
        title=(row.findtext("title") or "").strip()
        if not title or not begin or not end or end<=begin or end-begin>timedelta(hours=18):
            invalid+=1
            continue
        if begin < now + timedelta(hours=48) and end > now:
            count[cid]+=1
    if unexpected:
        raise ValueError("unrequested channel in targeted OSN grab: "+str(len(unexpected)))
    grouped={}
    for label in ("alfa","pinoy","radio"):
        subset=[cid for cid in FOCUS if group(cid)==label]
        grouped[label]={
            "ids":len(subset),"ids_with_future_programmes":sum(count[cid]>0 for cid in subset),
            "programmes_in_next_48h":sum(count[cid] for cid in subset),
        }
    return {
        "provider":"OSN Legacy",
        "focus_ids":len(FOCUS),
        "ids_with_future_programmes":sum(c>0 for c in count.values()),
        "missing":sorted(cid for cid,c in count.items() if c==0),
        "invalid_rows":invalid,
        "counts_by_id":count,
        "groups":grouped,
        "receiver_modified":False,
        "public_feeds_modified":False,
        "programmes_exported_to_output":False,
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    subs=ap.add_subparsers(dest="cmd",required=True)
    build=subs.add_parser("build")
    build.add_argument("--legacy-report",default="reports/osn-legacy-catalogue-probe.json")
    build.add_argument("--published-meta",default="feeds/osn.json")
    build.add_argument("--output",required=True)
    probe=subs.add_parser("inspect")
    probe.add_argument("--input",required=True)
    args=ap.parse_args()
    if args.cmd=="build":
        root=catalogue(load_json(args.legacy_report),load_json(args.published_meta))
        out=Path(args.output)
        out.parent.mkdir(parents=True,exist_ok=True)
        ET.indent(root,space="  ")
        out.write_bytes(ET.tostring(root,encoding="utf-8",xml_declaration=True))
        print(json.dumps({"focus":len(root),"alfa":len(ALFA),
                          "pinoy":len(PINOY),"radio":len(RADIO),
                          "status":"PRIVATE_RUNNER_CATALOGUE_ONLY","published":False}))
    else:
        root=ET.parse(args.input).getroot()
        print(json.dumps(inspect(root),sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
