#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final beIN MENA hybrid language pass.

Policy:
- beIN Movies / Series / Gourmet: English title/sub-title + Arabic description.
- beIN Sports / News / 4K / Max / Xtra: keep the already-approved Arabic sports
  title style (Arabic competition/programme names, Latin club/team names) and
  Arabic descriptions.

This runs AFTER bein_arabize.py / bein_ai_refine.py so sports normalization is
preserved. The English beIN guide is used only to replace titles for explicitly
hybrid entertainment IDs. No programme rows are invented.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

AR = re.compile(r"[\u0600-\u06FF]")
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


def read_root(path: str) -> ET.Element:
    data = Path(path).read_bytes()
    if path.endswith(".gz") or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return ET.fromstring(data)


def write_root(path: str, root: ET.Element) -> None:
    ET.indent(root, space="  ")
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if path.endswith(".gz"):
        Path(path).write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    else:
        Path(path).write_bytes(data)


def text_of(node: ET.Element, tag: str) -> str:
    for child in node.findall(tag):
        txt = (child.text or "").strip()
        if txt:
            return txt
    return ""


def is_arabic(text: str) -> bool:
    return bool(AR.search(text or ""))


def event_key(p: ET.Element):
    return (
        (p.get("channel") or "").strip(),
        (p.get("start") or "").strip(),
        (p.get("stop") or "").strip(),
    )


def start_key(p: ET.Element):
    return ((p.get("channel") or "").strip(), (p.get("start") or "").strip())


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


class Translator:
    def __init__(self, cache_path: str):
        self.path = Path(cache_path)
        try:
            self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except Exception:
            self.cache = {}
        self.new = 0
        self.failures = []

    def translate_ar(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text or is_arabic(text):
            return text
        key = "ar|" + text
        cached = self.cache.get(key)
        if cached and is_arabic(cached):
            return cached
        query = urlencode({"client":"gtx","sl":"auto","tl":"ar","dt":"t","q":text})
        req = Request(TRANSLATE_URL + "?" + query, headers={"User-Agent":"Mozilla/5.0 EPGManager/beIN"})
        for attempt in range(3):
            try:
                with urlopen(req, timeout=20) as r:
                    data = json.loads(r.read().decode("utf-8"))
                out = "".join(x[0] for x in data[0] if x and x[0]).strip()
                if out and is_arabic(out):
                    self.cache[key] = out
                    self.new += 1
                    time.sleep(0.12)
                    return out
            except Exception as e:
                if attempt == 2:
                    self.failures.append({"text":text[:160],"error":str(e)})
                else:
                    time.sleep(1.5 * (attempt + 1))
        return text

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_sports_title(node: ET.Element, tr: Translator) -> tuple[int, int]:
    """Normalize sports programme titles to Arabic while preserving participants.

    Team/club/player spans before a separator containing "vs" or " v " remain
    Latin. Other Latin-only segments (sport, event, magazine, competition) are
    translated segment-by-segment, so mixed titles cannot bypass the language
    policy merely because one Arabic segment is already present.
    """
    changed = 0
    remaining = 0
    for child in node.findall("title"):
        title = re.sub(r"\s+", " ", (child.text or "")).strip()
        if not title:
            continue
        if title.casefold() == "atp tennis":
            child.set("lang", "en")
            continue

        segments = [s.strip() for s in re.split(r"\s+-\s+", title)]
        out = []
        for i, seg in enumerate(segments):
            if not seg:
                continue
            # Preserve participant/matchup names in Latin script.
            if i == 0 and re.search(r"\s+(?:vs\.?|v)\s+", seg, re.I):
                out.append(seg)
                continue
            # Already Arabic: keep as-is.
            if is_arabic(seg) and not re.search(r"[A-Za-z]{3,}", seg):
                out.append(seg)
                continue
            # Mixed or Latin event/programme segment: translate it.
            if re.search(r"[A-Za-z]{3,}", seg):
                translated = tr.translate_ar(seg)
                if translated != seg and is_arabic(translated):
                    out.append(translated)
                    changed += 1
                else:
                    out.append(seg)
                    remaining += 1
            else:
                out.append(seg)
        child.text = " - ".join(out)
        if is_arabic(child.text or ""):
            child.set("lang", "ar")
    return changed, remaining

def ensure_arabic_desc(node: ET.Element, tr: Translator) -> tuple[int, int]:
    """Translate every non-Arabic description segment, including mixed rows.

    This fixes cases where an English paragraph followed by an Arabic metadata
    line (for example الموسم 2026/2027) was incorrectly treated as Arabic.
    """
    translated = 0
    remaining = 0
    for child in node.findall("desc"):
        raw = (child.text or "").strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.splitlines() if p.strip()]
        out = []
        for part in parts:
            # Pure Arabic segment: keep.
            if is_arabic(part) and not re.search(r"[A-Za-z]{4,}", part):
                out.append(part)
                continue
            # Anything carrying a real Latin sentence/phrase must become Arabic.
            if re.search(r"[A-Za-z]{4,}", part):
                new = tr.translate_ar(part)
                if new != part and is_arabic(new):
                    out.append(new)
                    translated += 1
                else:
                    out.append(part)
                    remaining += 1
            else:
                out.append(part)
        child.text = "\n".join(out)
        if is_arabic(child.text or ""):
            child.set("lang", "ar")
    return translated, remaining

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Processed beIN XML/XML.GZ after Arabic sports normalization")
    ap.add_argument("--english", required=True, help="Raw English guide for hybrid entertainment IDs")
    ap.add_argument("--policy", default="config/bein-language-policy.json")
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--cache", default="data/bein_hybrid_translation_cache.json")
    args = ap.parse_args()

    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    hybrid = set(policy.get("hybrid_ids", []))
    root = read_root(args.input)
    en_root = read_root(args.english)
    tr = Translator(args.cache)

    en_exact = {}
    en_start = defaultdict(list)
    for p in en_root.findall("programme"):
        cid = (p.get("channel") or "").strip()
        if cid not in hybrid:
            continue
        en_exact[event_key(p)] = p
        en_start[start_key(p)].append(p)

    stats = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "programmes": 0,
        "hybrid_programmes": 0,
        "sports_programmes": 0,
        "english_title_applied": 0,
        "english_title_missing": 0,
        "sports_titles_translated_fallback": 0,
        "sports_title_remaining_mismatch": 0,
        "arabic_description_present": 0,
        "arabic_description_missing": 0,
        "descriptions_translated_to_ar": 0,
        "description_language_remaining_mismatch": 0,
        "samples": {},
    }

    for p in root.findall("programme"):
        cid = (p.get("channel") or "").strip()
        if cid in hybrid:
            stats["hybrid_programmes"] += 1
            en = en_exact.get(event_key(p))
            if en is None:
                candidates = en_start.get(start_key(p), [])
                en = candidates[0] if candidates else None
            applied = False
            if en is not None:
                applied = replace_tag(p, en, "title", "en")
                replace_tag(p, en, "sub-title", "en")
            if applied:
                stats["english_title_applied"] += 1
            else:
                stats["english_title_missing"] += 1
        else:
            stats["sports_programmes"] += 1
            sport_changed, sport_remaining = ensure_sports_title(p, tr)
            stats["sports_titles_translated_fallback"] += sport_changed
            stats["sports_title_remaining_mismatch"] += sport_remaining

        changed, remaining = ensure_arabic_desc(p, tr)
        stats["descriptions_translated_to_ar"] += changed
        stats["description_language_remaining_mismatch"] += remaining
        title = text_of(p, "title")
        desc = text_of(p, "desc")
        if desc and is_arabic(desc):
            stats["arabic_description_present"] += 1
        else:
            stats["arabic_description_missing"] += 1

        if cid and cid not in stats["samples"]:
            stats["samples"][cid] = {
                "profile": "hybrid" if cid in hybrid else "sports_ar",
                "title": title,
                "description": desc[:260],
                "title_has_arabic": is_arabic(title),
                "description_has_arabic": is_arabic(desc),
            }
        stats["programmes"] += 1

    tr.save()
    stats["translation_cache_new"] = tr.new
    stats["translation_failures"] = tr.failures[:20]
    write_root(args.output, root)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in stats.items() if k!="samples"}, ensure_ascii=False))

    if stats["hybrid_programmes"] and stats["english_title_applied"] == 0:
        return 4
    return 0 if stats["programmes"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
