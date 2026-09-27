#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge STARZPLAY Arabic and English XMLTV into the EPGManager hybrid policy.

Arabic feed owns channel coverage, schedule times and Arabic descriptions.
International/foreign channels take English title/sub-title when the same event
exists in the English feed. Arabic-native channels remain fully Arabic.
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

import requests

AR = re.compile(r"[\u0600-\u06ff]")


def text_of(node: ET.Element, tag: str) -> str:
    for child in node.findall(tag):
        txt = (child.text or "").strip()
        if txt:
            return txt
    return ""


def channel_name(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return text_of(node, "display-name") or (node.get("id") or "")


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def event_key(p: ET.Element) -> tuple[str, str, str]:
    return ((p.get("channel") or "").strip(), (p.get("start") or "").strip(), (p.get("stop") or "").strip())


def start_key(p: ET.Element) -> tuple[str, str]:
    return ((p.get("channel") or "").strip(), (p.get("start") or "").strip())


def replace_tag(dst: ET.Element, src: ET.Element, tag: str, lang: str) -> bool:
    candidate = next((deepcopy(x) for x in src.findall(tag) if (x.text or "").strip()), None)
    if candidate is None:
        return False
    for old in list(dst.findall(tag)):
        dst.remove(old)
    candidate.set("lang", lang)
    dst.insert(0 if tag == "title" else min(1, len(dst)), candidate)
    return True


def ensure_lang(node: ET.Element, tag: str, lang: str) -> None:
    for child in node.findall(tag):
        if (child.text or "").strip():
            child.set("lang", lang)


def is_ar(text: str) -> bool:
    return bool(AR.search(text or ""))


def translate_ar(text: str, cache: dict[str, str]) -> str:
    raw = (text or "").strip()
    if not raw or is_ar(raw):
        return raw
    if raw in cache:
        return cache[raw]
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "ar", "dt": "t", "q": raw},
            timeout=12,
        )
        data = r.json()
        out = "".join(x[0] for x in data[0] if x and x[0]).strip()
        if out and is_ar(out):
            cache[raw] = out
            return out
    except Exception:
        pass
    cache[raw] = raw
    return raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arabic", required=True)
    ap.add_argument("--english", required=True)
    ap.add_argument("--policy", default="config/starzplay-language-policy.json")
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    ar_root = ET.parse(args.arabic).getroot()
    en_root = ET.parse(args.english).getroot()
    channels = {(c.get("id") or "").strip(): deepcopy(c) for c in ar_root.findall("channel") if (c.get("id") or "").strip()}
    en_channels = {(c.get("id") or "").strip(): c for c in en_root.findall("channel") if (c.get("id") or "").strip()}

    ar_native_ids = set(policy.get("arabic_native_ids", []))
    hybrid_ids = set(policy.get("hybrid_ids", []))
    arabic_display_name_ids = set(policy.get("arabic_display_name_ids", []))
    force_arabic_content_ids = set(policy.get("force_arabic_content_ids", []))
    translation_cache: dict[str, str] = {}

    # IDs stay stable for existing EPGManager mappings. Only the human-readable
    # channel label is switched to the English STARZPLAY catalogue. The one
    # explicit exception is National Geographic Abu Dhabi, which stays 100% AR.
    english_channel_names_applied = 0
    english_channel_names_missing = 0
    for cid, node in channels.items():
        if cid in arabic_display_name_ids:
            ensure_lang(node, "display-name", "ar")
            continue
        en_node = en_channels.get(cid)
        en_name = channel_name(en_node)
        if en_node is not None and en_name:
            for old in list(node.findall("display-name")):
                node.remove(old)
            dn = ET.Element("display-name", {"lang": "en"})
            dn.text = en_name
            node.insert(0, dn)
            english_channel_names_applied += 1
        else:
            english_channel_names_missing += 1
    ar_tokens = [norm(x) for x in policy.get("arabic_native_name_tokens", [])]
    hy_tokens = [norm(x) for x in policy.get("hybrid_name_tokens", [])]
    default_profile = policy.get("default_profile", "arabic_native")

    def profile(cid: str) -> str:
        if cid in ar_native_ids:
            return "arabic_native"
        if cid in hybrid_ids:
            return "hybrid"
        # Classification must not depend only on the Arabic localized
        # display-name. The English page is the reliable signal for international
        # channel brands such as National Geographic, CNN, Cartoon Network, Zee
        # and STARZPLAY thematic channels.
        name_ar = norm(channel_name(channels.get(cid)))
        name_en = norm(channel_name(en_channels.get(cid)))
        names = " | ".join(x for x in (name_ar, name_en) if x)
        if any(tok and tok in names for tok in ar_tokens):
            return "arabic_native"
        if any(tok and tok in names for tok in hy_tokens):
            return "hybrid"
        return default_profile

    en_exact = {}
    en_start = defaultdict(list)
    for p in en_root.findall("programme"):
        en_exact[event_key(p)] = p
        en_start[start_key(p)].append(p)

    out = ET.Element("tv", {
        "generator-info-name": "EPGManager STARZPLAY hybrid EN-title AR-description",
        "generator-info-url": "https://www.starzplay.com/",
    })
    for cid in sorted(channels, key=str.casefold):
        out.append(deepcopy(channels[cid]))

    stats = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "channels": len(channels),
        "programmes": 0,
        "hybrid_programmes": 0,
        "arabic_native_programmes": 0,
        "english_title_applied": 0,
        "english_title_missing": 0,
        "arabic_description_present": 0,
        "arabic_description_missing": 0,
        "english_channel_names_applied": english_channel_names_applied,
        "english_channel_names_missing": english_channel_names_missing,
        "arabic_display_name_ids": sorted(arabic_display_name_ids),
        "force_arabic_content_ids": sorted(force_arabic_content_ids),
        "translations_cached": 0,
        "profiles": {},
        "samples": {},
    }

    for p in ar_root.findall("programme"):
        cid = (p.get("channel") or "").strip()
        if cid not in channels:
            continue
        node = deepcopy(p)
        prof = profile(cid)
        stats["profiles"][cid] = prof
        if prof == "hybrid":
            stats["hybrid_programmes"] += 1
            en = en_exact.get(event_key(p))
            if en is None:
                candidates = en_start.get(start_key(p), [])
                en = candidates[0] if candidates else None
            applied = bool(en is not None and replace_tag(node, en, "title", "en"))
            if en is not None:
                replace_tag(node, en, "sub-title", "en")
            if applied:
                stats["english_title_applied"] += 1
            else:
                stats["english_title_missing"] += 1
            ensure_lang(node, "desc", "ar")
        else:
            stats["arabic_native_programmes"] += 1
            if cid in force_arabic_content_ids:
                for tag in ("title", "sub-title", "desc"):
                    for child in node.findall(tag):
                        raw = (child.text or "").strip()
                        if raw and not is_ar(raw):
                            child.text = translate_ar(raw, translation_cache)
            ensure_lang(node, "title", "ar")
            ensure_lang(node, "sub-title", "ar")
            ensure_lang(node, "desc", "ar")

        for child in list(node.findall("desc")):
            txt = (child.text or "").strip()
            if txt and not is_ar(txt):
                node.remove(child)
        desc = text_of(node, "desc")
        if desc and is_ar(desc):
            stats["arabic_description_present"] += 1
        else:
            stats["arabic_description_missing"] += 1
        if cid not in stats["samples"]:
            stats["samples"][cid] = {
                "profile": prof,
                "title": text_of(node, "title"),
                "description": desc[:240],
            }
        out.append(node)
        stats["programmes"] += 1

    stats["translations_cached"] = len(translation_cache)
    ET.indent(out, space="  ")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(ET.tostring(out, encoding="utf-8", xml_declaration=True))
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k not in {"profiles", "samples"}}, ensure_ascii=False))
    if stats["hybrid_programmes"] and not stats["english_title_applied"]:
        return 4
    return 0 if stats["programmes"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
