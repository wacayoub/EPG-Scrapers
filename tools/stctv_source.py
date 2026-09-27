#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Low-rate STC TV public metadata XMLTV source.

Receiver policy:
- keep every TV channel ID exposed by the STC public channel catalogue;
- scrape schedules sequentially once per run, without parallel fan-out;
- channels with no programme in the current window stay in XMLTV/index and are
  reported as zero-EPG instead of being deleted;
- timestamps come from STC epoch milliseconds and are emitted as UTC +0000.

Uses only public guest metadata loaded by web.stctv.com. No playback, DRM,
account login or entitlement bypass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
APP_KEY = "webB2CGDMPrdExy0sVDlZMzNDdUyZ"
SCHEDULE_KEY = "GDMPrdExy0sVDlZMzNDdUyZ"
CHANNELS_API = f"https://jawwy2-prod-cdn.intigral-ott.net/bolt/v2/{APP_KEY}/channels"
SCHEDULE_BASE = "https://prod-cdn-content-api.intigral-ott.net/content-api-3.0.1/channels/schedules"
AR = re.compile(r"[\u0600-\u06ff]")
NONWORD = re.compile(r"[^a-z0-9]+")

ALIASES = {
    "starzplay sports 1": "StarzplaySports1.sa@HD",
    "starzplay sports 2": "StarzplaySports2.sa@HD",
    "starzplay sports 3": "StarzplaySports3.sa@HD",
    "mbc": "MBC1.sa@HD",
    "mbc 2": "MBC2.sa@HD",
    "mbc 3": "MBC3.sa@HD",
    "mbc 4": "MBC4.sa@HD",
    "mbc action": "MBCAction.sa@HD",
    "mbc max": "MBCMax.sa@HD",
    "mbc bollywood": "MBCBollywood.sa@HD",
    "mbc drama": "MBCDrama.sa@HD",
    "mbc masr": "MBCMasr.eg@HD",
    "mbc masr 2": "MBCMasr2.eg@HD",
    "wanasah": "Wanasah.ae@SD",
    "al arabiya": "AlArabiya.sa@HD",
}
HYBRID_TOKENS = (
    "starzplay sports",
    "mbc 2",
    "mbc max",
    "mbc 4",
    "mbc action",
    "mbc bollywood",
    "mbc variety",
)
CANONICAL_OVERRIDE = {
    "starzplay sports 1": "StarzplaySports1.sa@HD",
    "starzplay sports 2": "StarzplaySports2.sa@HD",
    "starzplay sports 3": "StarzplaySports3.sa@HD",
    "al arabiya": "AlArabiya.sa@HD",
    "al arabiya business": "AlArabiyaBusiness.ae@SD",
    "wanasah": "Wanasah.ae@SD",
}


def norm(s):
    return " ".join(NONWORD.sub(" ", (s or "").casefold()).split())


def read_index(path):
    out = {}
    p = Path(path) if path else None
    if not p or not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "|" not in line:
            continue
        cid, name = line.split("|", 1)
        if cid.strip() and name.strip():
            out.setdefault(norm(name), cid.strip())
    return out


def xml_id(name, index, sid=""):
    n = norm(name)
    if n in CANONICAL_OVERRIDE:
        return CANONICAL_OVERRIDE[n]
    if n in index:
        return index[n]
    if n in ALIASES:
        return ALIASES[n]
    for k, v in ALIASES.items():
        if n == k or n.startswith(k + " "):
            return v
    # Use STC's stable source ID in the fallback so identically named regional
    # variants cannot collapse onto the same XMLTV ID.
    seed = n + "|" + str(sid or "")
    return "stctv." + hashlib.sha1(seed.encode()).hexdigest()[:12]


def get_json(s, url, params, timeout):
    r = s.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_channels(data):
    d = data.get("data") if isinstance(data, dict) else None
    return d.get("channels", []) if isinstance(d, dict) and isinstance(d.get("channels"), list) else []


def rows(data):
    out = []
    if isinstance(data, list):
        for b in data:
            if isinstance(b, dict) and isinstance(b.get("listings"), list):
                out.extend(b["listings"])
    return out


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--id-index", default="feeds/mena.txt")
    ap.add_argument("--window-hours", type=int, default=48)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument(
        "--max-channels",
        type=int,
        default=0,
        help="0 keeps the complete STC source catalogue; positive values are diagnostic caps only",
    )
    ap.add_argument(
        "--profile",
        choices=("all", "starzplay-sports"),
        default="all",
        help="all keeps every STC channel; starzplay-sports is retained only for diagnostics",
    )
    ap.add_argument(
        "--catalogue-only",
        action="store_true",
        help="fetch the complete STC channel catalogue but do not request per-channel schedules",
    )
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=max(1, args.window_hours))
    days = []
    d = now.date()
    while datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) < end + timedelta(days=1):
        days.append(d.isoformat())
        d += timedelta(days=1)

    index = read_index(args.id_index)
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.7",
            "Origin": "https://web.stctv.com",
            "Referer": "https://web.stctv.com/",
        }
    )

    root = ET.Element(
        "tv",
        {
            "generator-info-name": "EPGManager STC TV public low-rate",
            "generator-info-url": "https://web.stctv.com/",
        },
    )
    stats = {
        "generated_utc": now.isoformat(),
        "channels": 0,
        "channels_with_epg": 0,
        "programmes": 0,
        "requests": 0,
        "source_channels": 0,
        "source_metadata_issues": [],
        "zero_epg": [],
        "hybrid_channels": [],
        "samples": {},
        "timezone_output": "UTC +0000",
    }

    try:
        data = get_json(
            sess,
            CHANNELS_API,
            {"country": "SA", "deviceType": "web", "filter": "", "device": "PC", "appKey": APP_KEY},
            args.timeout,
        )
        stats["requests"] += 1
        targets = list(get_channels(data))
        stats["source_channels"] = len(targets)

        if args.profile == "starzplay-sports":
            targets = [
                ch
                for ch in targets
                if norm(str(ch.get("channelTitle") or ch.get("channelTitleAr") or "")).startswith(
                    "starzplay sports "
                )
            ]
        if args.max_channels and args.max_channels > 0:
            targets = targets[: args.max_channels]

        stats["profile"] = args.profile
        stats["selected_channels"] = len(targets)

        seen_cids = set()
        prepared = []
        for source_index, ch in enumerate(targets):
            title_en = str(ch.get("channelTitle") or "").strip()
            title_ar = str(ch.get("channelTitleAr") or "").strip()
            sid = str(ch.get("channelID") or "").strip()
            name = title_en or title_ar
            if not sid:
                stats["source_metadata_issues"].append({
                    "source_index": source_index,
                    "name": name,
                    "reason": "missing_channelID",
                    "retained": False,
                })
                continue
            if not name:
                # A valid STC channelID must never disappear just because the
                # current catalogue omitted both display-title fields.
                name = f"STC TV {sid}"
                stats["source_metadata_issues"].append({
                    "source_index": source_index,
                    "channelID": sid,
                    "reason": "missing_title_placeholder_used",
                    "retained": True,
                })
            cid = xml_id(name, index, sid)
            if cid in seen_cids:
                # Two STC source entries may legitimately share the same
                # display name/canonical alias (regional or package variants).
                # Never drop the second source ID: keep the canonical ID for
                # the first occurrence and give subsequent variants a stable
                # source-ID-based local identifier.
                seed = norm(name) + "|" + sid
                cid = "stctv." + hashlib.sha1(seed.encode()).hexdigest()[:12]
                bump = 1
                while cid in seen_cids:
                    cid = "stctv." + hashlib.sha1((seed + f"|{bump}").encode()).hexdigest()[:12]
                    bump += 1
            seen_cids.add(cid)
            prof = "hybrid" if any(tok in norm(name) for tok in HYBRID_TOKENS) else "arabic_native"
            prepared.append((ch, name, sid, cid, prof))

            c = ET.SubElement(root, "channel", {"id": cid})
            ET.SubElement(c, "display-name", {"lang": "en"}).text = name
            ar_name = str(ch.get("channelTitleAr") or "").strip()
            if ar_name:
                ET.SubElement(c, "display-name", {"lang": "ar"}).text = ar_name
            ET.SubElement(c, "url", {"system": "stctv-id"}).text = sid
            stats["channels"] += 1
            if prof == "hybrid":
                stats["hybrid_channels"].append(cid)

        stats["catalogue_only"] = bool(args.catalogue_only)
        if args.catalogue_only:
            prepared = []

        for ci, (ch, name, sid, cid, prof) in enumerate(prepared):
            allrows = []
            for di, date in enumerate(days):
                try:
                    data2 = get_json(
                        sess,
                        f"{SCHEDULE_BASE}/{date}/3",
                        {"apikey": SCHEDULE_KEY, "productKey": "stc-tv", "byId": sid},
                        args.timeout,
                    )
                    stats["requests"] += 1
                    allrows.extend(rows(data2))
                except Exception:
                    pass
                if di + 1 < len(days):
                    time.sleep(max(0, args.delay))

            seen = set()
            keep = []
            for li in allrows:
                st = int(li.get("startTime") or 0)
                et = int(li.get("endTime") or 0)
                if not st or not et:
                    continue
                sdt = datetime.fromtimestamp(st / 1000, tz=timezone.utc)
                edt = datetime.fromtimestamp(et / 1000, tz=timezone.utc)
                if sdt >= end or edt <= now - timedelta(hours=1):
                    continue
                key = (st, et, str(li.get("listingId") or li.get("title") or ""))
                if key in seen:
                    continue
                seen.add(key)
                keep.append(li)

            if keep:
                stats["channels_with_epg"] += 1
                for li in sorted(keep, key=lambda x: int(x.get("startTime") or 0)):
                    lt = li.get("localizedTitle") or {}
                    ld = li.get("localizedDescription") or {}
                    en_title = str(li.get("title") or "").strip()
                    ar_title = str(lt.get("ar") or "").strip() if isinstance(lt, dict) else ""
                    ar_desc = str(ld.get("ar") or "").strip() if isinstance(ld, dict) else ""
                    if prof == "hybrid":
                        title = en_title or ar_title
                        lang = "en" if en_title else "ar"
                    else:
                        title = ar_title or en_title
                        lang = "ar" if ar_title else "en"
                    if not title:
                        continue
                    p = ET.SubElement(
                        root,
                        "programme",
                        {
                            "channel": cid,
                            "start": fmt(int(li["startTime"])),
                            "stop": fmt(int(li["endTime"])),
                        },
                    )
                    ET.SubElement(p, "title", {"lang": lang}).text = title
                    if ar_desc:
                        ET.SubElement(p, "desc", {"lang": "ar"}).text = ar_desc
                    stats["programmes"] += 1
                    if cid not in stats["samples"]:
                        stats["samples"][cid] = {
                            "name": name,
                            "profile": prof,
                            "title": title,
                            "desc": ar_desc[:220],
                        }
            else:
                stats["zero_epg"].append({"id": cid, "name": name})

            if ci + 1 < len(prepared):
                time.sleep(max(0, args.delay))

    except Exception as e:
        stats["error"] = str(e)

    ET.indent(root, space="  ")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "samples"}, ensure_ascii=False))
    if args.catalogue_only:
        return 0 if stats["channels"] else 11
    return 0 if stats["channels"] and stats["programmes"] else 11


if __name__ == "__main__":
    raise SystemExit(main())
