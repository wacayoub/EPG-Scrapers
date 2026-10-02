#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect OSN's public TV-guide frontend for the internal Other-box API value."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
import cloudscraper

PAGE = "https://www.osn.com/ar-sa/watch/tv-schedule"
OUT = Path("reports/osn-frontend-probe.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36 EPGManager-OSN-Probe/1.0"
KEYWORDS = (
    "Other boxes",
    "Android box",
    "apidata/channels",
    "tv-schedule-timeline",
    "boxAndroid",
    "platform=",
    "other",
    "android",
)

def contexts(text: str, term: str, radius: int = 350) -> list[str]:
    out = []
    low = text.casefold()
    needle = term.casefold()
    pos = 0
    while True:
        i = low.find(needle, pos)
        if i < 0:
            break
        out.append(text[max(0, i-radius):min(len(text), i+len(term)+radius)])
        pos = i + len(term)
        if len(out) >= 20:
            break
    return out

def main() -> int:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.7"})
    html = ""
    page_status = None
    for client in (s, cloudscraper.create_scraper()):
        try:
            page = client.get(PAGE, timeout=30, headers={"User-Agent": UA, "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.7"})
            page_status = page.status_code
            if page.status_code == 200:
                html = page.text
                break
        except Exception:
            continue

    srcs = set(re.findall(r'''(?:src|href)=["']([^"']+\.js(?:\?[^"']*)?)["']''', html))
    # Next.js can also serialize chunk paths inside the page payload.
    srcs.update(re.findall(r'''["']([^"']*/_next/static/[^"']+\.js(?:\?[^"']*)?)["']''', html))
    urls = sorted({urljoin(PAGE, x.replace("\\/", "/")) for x in srcs})

    # Always inspect the chunk referenced by the current upstream OSN adapter.
    urls.append("https://www.osn.com/_next/static/chunks/87cf1e375968671c.js")
    urls = sorted(set(urls))

    report = {
        "page": PAGE,
        "http_status": page_status,
        "scripts_discovered": len(urls),
        "hits": [],
        "candidate_platform_literals": [],
    }

    texts = [("page", PAGE, html)] if html else []
    for url in urls[:80]:
        try:
            r = s.get(url, timeout=25)
            if r.status_code != 200:
                continue
            texts.append(("script", url, r.text))
        except Exception as exc:
            report.setdefault("errors", []).append({"url": url, "error": str(exc)})

    candidates = set()
    for kind, url, text in texts:
        matched = False
        item = {"kind": kind, "url": url, "matches": {}}
        for kw in KEYWORDS:
            cc = contexts(text, kw)
            if cc:
                matched = True
                item["matches"][kw] = cc[:8]

        # Common patterns around API query construction and UI option objects.
        patterns = [
            r'''platform\s*[:=]\s*["']([^"']+)["']''',
            r'''platform=([A-Za-z0-9_-]+)''',
            r'''box([A-Za-z0-9_-]+)''',
            r'''(?:label|title|name)\s*:\s*["']Other(?: boxes)?["'][^}]{0,250}?(?:value|id|key)\s*:\s*["']([^"']+)["']''',
            r'''(?:value|id|key)\s*:\s*["']([^"']+)["'][^}]{0,250}?(?:label|title|name)\s*:\s*["']Other(?: boxes)?["']''',
        ]
        local = set()
        for pat in patterns:
            for m in re.finditer(pat, text, flags=re.I):
                if m.groups():
                    val = m.group(1)
                    if 0 < len(val) < 80:
                        local.add(val)
                        candidates.add(val)
        if local:
            item["candidate_literals"] = sorted(local)
            matched = True
        if matched:
            report["hits"].append(item)

    report["candidate_platform_literals"] = sorted(candidates)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("OSN_FRONTEND_PROBE scripts=", report["scripts_discovered"])
    print("OSN_FRONTEND_CANDIDATES", json.dumps(report["candidate_platform_literals"], ensure_ascii=False))
    for item in report["hits"]:
        print("OSN_FRONTEND_HIT", item["url"])
        if item.get("candidate_literals"):
            print("  candidates=", ",".join(item["candidate_literals"]))
        for kw, chunks in item.get("matches", {}).items():
            if kw.casefold() in {"other boxes", "android box", "apidata/channels", "platform=", "boxandroid"}:
                for chunk in chunks[:3]:
                    one = re.sub(r"\s+", " ", chunk)
                    print(f"  {kw}: {one[:900]}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
