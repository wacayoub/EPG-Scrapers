#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPG.pw 2M API source probe; NO download persistence or publication.

User-provided URL: https://epg.pw/api/epg.xml?channel_id=445700
Program listings remain in transient process memory and are NEVER saved,
printed, translated, republished, or merged into XMLTV. The provider's Terms
prohibit redistribution/copying without permission. Use only for assessment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import re
from urllib import robotparser, request, error
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

BASE = "https://epg.pw"
XML = BASE + "/api/epg.xml?channel_id=445700"
JSON = BASE + "/api/epg.json?channel_id=445700"
UA = "EPGManager-2M-Source-Assessment/1.0"
MAX_BYTES = 4 * 1024 * 1024
XML_DATETIME = re.compile(r"^(\d{14})\s+([+-]\d{4})$")
EXPECTED = "2M Maroc"

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def read_once(url, opener=None):
    if url not in (XML, JSON):
        raise ValueError("unauthorized target")
    rules = robotparser.RobotFileParser()
    rules.set_url(BASE + "/robots.txt")
    # Fail closed for missing/unavailable robots information.
    rules.read()
    if not rules.can_fetch(UA, url):
        raise PermissionError("robots disallows request, or policy unavailable")
    req = request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml,application/json"})
    connection = opener or request.build_opener(request.ProxyHandler({}), NoRedirect)
    with connection.open(req, timeout=12) as response:
        if response.url != url:
            raise ValueError("redirected source, refused")
        buf = response.read(MAX_BYTES+1)
    if len(buf) > MAX_BYTES:
        raise ValueError("API response size exceeds bound")
    return buf

def dt(value):
    if not isinstance(value, str):
        return None
    match = XML_DATETIME.fullmatch(value)
    if not match:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S %z").astimezone(timezone.utc)
    except ValueError:
        return None

def inspect_xml(raw, now):
    """Pure validator from bytes to counts; never outputs event text or guide."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("invalid XMLTV input")
    root = ET.fromstring(raw)
    if root.tag != "tv":
        raise ValueError("not XMLTV root")
    channels = root.findall("channel")
    if not (1 <= len(channels) <= 3):
        raise ValueError("unusual number of channel IDs")
    display = " ".join((n.text or "").strip() for c in channels
                       for n in c.findall("display-name")).casefold()
    names_good = "2m" in display and "maroc" in display
    valid_ids = {c.get("id") for c in channels if c.get("id")}
    if not valid_ids:
        raise ValueError("XMLTV missing channel identities")
    seen = 0
    bad = 0
    current = 0
    next48 = 0
    anchor = []
    stamps = []
    title_missing = 0
    foreign = 0
    for event in root.findall("programme"):
        seen += 1
        if seen > 1500:
            raise ValueError("unexpected number of programmes for 2M")
        if event.get("channel") not in valid_ids:
            foreign += 1
            continue
        begin = dt(event.get("start"))
        stop = dt(event.get("stop"))
        title = (event.findtext("title") or "").strip()
        if not title:
            title_missing += 1
        if begin is None or stop is None or not begin < stop or stop-begin > timedelta(hours=8):
            bad += 1
            continue
        stamps.append((begin, stop))
        if begin <= now < stop and title:
            current += 1
        if stop > now and begin < now + timedelta(hours=48) and title:
            next48 += 1
        if title.casefold().strip() == "info soir":
            anchor.append(begin.strftime("%Y-%m-%dT%H:%MZ"))
    stamps.sort()
    return {
        "format":"XMLTV","channel_name_matches_2m_maroc":names_good,
        "channel_ids":len(valid_ids),
        "events_seen":seen, "bad_times":bad, "untitled":title_missing,
        "events_with_other_channel_id":foreign,
        "events_current":current, "events_future_48h":next48,
        "first_start_utc":stamps[0][0].isoformat() if stamps else None,
        "last_stop_utc":max(b for _,b in stamps).isoformat() if stamps else None,
        "info_soir_start_utc_samples":anchor[:3],
        "xmltv_now_and_future_present":bool(current and next48),
        "timezone_alignment_verified":False,
        "redistribution_authorized":False,
    }

def inspect_json(raw, now):
    if not isinstance(raw,bytes) or len(raw)>MAX_BYTES:
        raise ValueError("invalid JSON response")
    data=json.loads(raw)
    if not isinstance(data,dict):
        raise ValueError("unexpected JSON")
    entries=data.get("epg_list")
    if not isinstance(entries,list) or len(entries)>1500:
        raise ValueError("missing or oversized JSON guide")
    starts=[]
    anchors=[]
    for e in entries:
        if not isinstance(e,dict):
            continue
        iso=e.get("start_date")
        try:
            t=datetime.fromisoformat(iso.replace("Z","+00:00"))
            if t.tzinfo is None:
                continue
            t=t.astimezone(timezone.utc)
        except (TypeError,ValueError,AttributeError):
            continue
        starts.append(t)
        if str(e.get("title") or "").casefold().strip()=="info soir":
            anchors.append(t.strftime("%Y-%m-%dT%H:%MZ"))
    return {
        "channel_name_matches_2m_maroc":data.get("name")==EXPECTED,
        "entries":len(entries),
        "valid_utc_starts":len(starts),
        "first_start_utc":min(starts).isoformat() if starts else None,
        "last_start_utc":max(starts).isoformat() if starts else None,
        "future_starts_in_48h":sum(now <= t < now+timedelta(hours=48) for t in starts),
        "info_soir_start_utc_samples":anchors[:3],
        "source_date":data.get("end_date"),
        "timezone_alignment_verified":False,
        "redistribution_authorized":False,
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    report={
        "audit":"EPG.pw 2M direct-API assessment",
        "checked_utc":now.isoformat(),"source_channel_id":"445700",
        "read_only":True,"receiver_modified":False,
        "provider_epg_republished":False,"production_source_enabled":False,
        "license":"PERSONAL_ACCESS_ONLY__NO_REPUBLICATION_AUTHORIZED",
    }
    if args.live:
        for fmt,url,assess in (("xml",XML,inspect_xml),("json",JSON,inspect_json)):
            try:
                report[fmt]=assess(read_once(url),now)
                report[fmt]["status"]="INSPECTED"
            except (PermissionError,OSError,error.URLError,TimeoutError,ValueError,
                    UnicodeError,ET.ParseError,json.JSONDecodeError) as e:
                report[fmt]={"status":"NOT_VERIFIED",
                             "reason_type":type(e).__name__}
    else:
        report["status"]="NO_NETWORK_DEFAULT"
    print(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
