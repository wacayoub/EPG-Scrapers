#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ElCinema hybrid language builder.

Hybrid channels: English title/sub-title + Arabic description.
Arabic-native channels: Arabic title/sub-title + Arabic description.

The Arabic scrape remains authoritative for schedules and descriptions.
The English ElCinema guide is used only for titles of explicitly hybrid IDs.
No programme rows or translations are invented.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

AR = re.compile(r"[\u0600-\u06FF]")


def read_root(path: str) -> ET.Element:
    return ET.parse(path).getroot()


def text_of(node: ET.Element, tag: str) -> str:
    for child in node.findall(tag):
        txt = (child.text or "").strip()
        if txt:
            return txt
    return ""


def is_arabic(text: str) -> bool:
    return bool(AR.search(text or ""))


def copy(node: ET.Element) -> ET.Element:
    return deepcopy(node)


def replace_tag(dst: ET.Element, src: ET.Element, tag: str, lang: str) -> bool:
    candidate = None
    for child in src.findall(tag):
        if (child.text or "").strip():
            candidate = deepcopy(child)
            break
    if candidate is None:
        return False
    for child in list(dst.findall(tag)):
        dst.remove(child)
    candidate.set("lang", lang)
    dst.insert(0 if tag == "title" else min(1, len(dst)), candidate)
    return True


def ensure_lang(node: ET.Element, tag: str, lang: str) -> None:
    for child in node.findall(tag):
        if (child.text or "").strip():
            child.set("lang", lang)


def enforce_arabic_description(node: ET.Element) -> int:
    removed = 0
    for child in list(node.findall("desc")):
        txt = (child.text or "").strip()
        if txt and not is_arabic(txt):
            node.remove(child)
            removed += 1
    return removed


def event_key(p: ET.Element):
    return (
        (p.get("channel") or "").strip(),
        (p.get("start") or "").strip(),
        (p.get("stop") or "").strip(),
    )


def start_key(p: ET.Element):
    return ((p.get("channel") or "").strip(), (p.get("start") or "").strip())


def build_catalogue(fallback_catalogue: str, policy_path: str, output: str) -> int:
    policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    wanted = set(policy.get("hybrid_ids", []))
    root = read_root(fallback_catalogue)
    out = ET.Element("channels")
    found = set()
    for ch in root.findall("channel"):
        cid = (ch.get("xmltv_id") or ch.get("id") or "").strip()
        if cid in wanted:
            out.append(copy(ch))
            found.add(cid)
    ET.indent(out, space="  ")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes(ET.tostring(out, encoding="utf-8", xml_declaration=True))
    missing = sorted(wanted - found)
    print(json.dumps({
        "hybrid_requested": len(wanted),
        "hybrid_catalogue": len(out),
        "missing": missing,
    }, ensure_ascii=False))
    return 0 if len(out) and not missing else 3


def merge(arabic: str, english: str, policy_path: str, output: str, report: str) -> int:
    policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    hybrid = set(policy.get("hybrid_ids", []))
    ar_root = read_root(arabic)
    en_root = read_root(english)

    en_exact = {}
    en_start = defaultdict(list)
    for p in en_root.findall("programme"):
        cid = (p.get("channel") or "").strip()
        if not cid:
            continue
        en_exact[event_key(p)] = p
        en_start[start_key(p)].append(p)

    out = ET.Element("tv", {
        "generator-info-name": "EPGManager ElCinema hybrid EN-title AR-description",
        "generator-info-url": "https://github.com/wacayoub/EPG-Scrapers",
    })
    for ch in ar_root.findall("channel"):
        out.append(copy(ch))

    stats = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "programmes": 0,
        "hybrid_programmes": 0,
        "arabic_native_programmes": 0,
        "english_title_applied": 0,
        "english_title_missing": 0,
        "arabic_description_present": 0,
        "arabic_description_missing": 0,
        "non_arabic_description_removed": 0,
        "samples": {},
    }

    for p in ar_root.findall("programme"):
        cid = (p.get("channel") or "").strip()
        node = copy(p)
        if cid in hybrid:
            stats["hybrid_programmes"] += 1
            en = en_exact.get(event_key(p))
            if en is None:
                candidates = en_start.get(start_key(p), [])
                en = candidates[0] if candidates else None
            applied = False
            if en is not None:
                applied = replace_tag(node, en, "title", "en")
                replace_tag(node, en, "sub-title", "en")
            if applied:
                stats["english_title_applied"] += 1
            else:
                stats["english_title_missing"] += 1
            ensure_lang(node, "desc", "ar")
        else:
            stats["arabic_native_programmes"] += 1
            ensure_lang(node, "title", "ar")
            ensure_lang(node, "sub-title", "ar")
            ensure_lang(node, "desc", "ar")

        stats["non_arabic_description_removed"] += enforce_arabic_description(node)
        title = text_of(node, "title")
        desc = text_of(node, "desc")
        if desc and is_arabic(desc):
            stats["arabic_description_present"] += 1
        else:
            stats["arabic_description_missing"] += 1

        if cid and cid not in stats["samples"]:
            stats["samples"][cid] = {
                "profile": "hybrid" if cid in hybrid else "arabic_native",
                "title": title,
                "description": desc[:240],
                "title_has_arabic": is_arabic(title),
                "description_has_arabic": is_arabic(desc),
            }
        out.append(node)
        stats["programmes"] += 1

    ET.indent(out, space="  ")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes(ET.tostring(out, encoding="utf-8", xml_declaration=True))
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({k:v for k,v in stats.items() if k!="samples"}, ensure_ascii=False))
    if stats["hybrid_programmes"] and stats["english_title_applied"] == 0:
        return 4
    return 0 if stats["programmes"] else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("catalogue")
    c.add_argument("--fallback-catalogue", required=True)
    c.add_argument("--policy", required=True)
    c.add_argument("--output", required=True)

    m = sub.add_parser("merge")
    m.add_argument("--arabic", required=True)
    m.add_argument("--english", required=True)
    m.add_argument("--policy", required=True)
    m.add_argument("--output", required=True)
    m.add_argument("--report", required=True)

    args = ap.parse_args()
    if args.cmd == "catalogue":
        return build_catalogue(args.fallback_catalogue, args.policy, args.output)
    return merge(args.arabic, args.english, args.policy, args.output, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
