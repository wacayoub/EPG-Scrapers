#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect OSN's public TV-guide frontend for the internal Other-box API value."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import cloudscraper
import requests

PAGES = [
    "https://www.osn.com/en-ae/watch/tv-schedule",
    "https://www.osn.com/ar-ae/watch/tv-schedule",
    "https://www.osn.com/en-sa/watch/tv-schedule",
    "https://www.osn.com/ar-sa/watch/tv-schedule",
]
OUT = Path("reports/osn-frontend-probe.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36 EPGManager-OSN-Probe/1.1"
KEYWORDS = (
    "Other boxes",
    "Other box",
    "Android box",
    "Android",
    "apidata/channels",
    "tv-schedule-timeline",
    "boxAndroid",
    "platform=",
    "platform",
)

def contexts(text: str, term: str, radius: int = 550, limit: int = 12) -> list[str]:
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
        if len(out) >= limit:
            break
    return out

def get(session, url: str):
    try:
        r = session.get(
            url,
            timeout=30,
            headers={"User-Agent": UA, "Accept-Language": "en-AE,en;q=0.9,ar;q=0.7"},
        )
        return r
    except Exception:
        return None

def extract_candidates(text: str) -> set[str]:
    out = set()
    patterns = [
        r'''[?&]platform=([A-Za-z0-9_.-]+)''',
        r'''platform\s*[:=]\s*["']([A-Za-z0-9_.-]+)["']''',
        r'''["']platform["']\s*:\s*["']([A-Za-z0-9_.-]+)["']''',
        r'''box([A-Z][A-Za-z0-9_-]+)''',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.I):
            val = m.group(1)
            if 0 < len(val) < 80 and not val.startswith("-"):
                out.add(val)
    return out

def main() -> int:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    cloud = cloudscraper.create_scraper()
    src_urls: set[str] = set()
    texts: list[tuple[str, str, str]] = []
    pages_meta = []

    for page_url in PAGES:
        html = ""
        status = None
        for client in (s, cloud):
            r = get(client, page_url)
            if r is None:
                continue
            status = r.status_code
            if r.status_code == 200:
                html = r.text
                break
        pages_meta.append({"url": page_url, "status": status, "bytes": len(html)})
        if not html:
            continue
        texts.append(("page", page_url, html))
        srcs = set(re.findall(r'''(?:src|href)=["']([^"']+\.js(?:\?[^"']*)?)["']''', html))
        srcs.update(re.findall(r'''["']([^"']*/_next/static/[^"']+\.js(?:\?[^"']*)?)["']''', html))
        src_urls.update(urljoin(page_url, x.replace("\\/", "/")) for x in srcs)

    # Known chunk referenced by upstream iptv-org adapter.
    src_urls.add("https://www.osn.com/_next/static/chunks/87cf1e375968671c.js")

    scripts_meta = []
    for url in sorted(src_urls)[:120]:
        r = get(cloud, url) or get(s, url)
        if r is None:
            scripts_meta.append({"url": url, "status": None, "bytes": 0})
            continue
        scripts_meta.append({"url": url, "status": r.status_code, "bytes": len(r.content)})
        if r.status_code == 200:
            texts.append(("script", url, r.text))

    report = {
        "pages": pages_meta,
        "scripts_discovered": len(src_urls),
        "scripts": scripts_meta,
        "hits": [],
        "candidate_platform_literals": [],
    }

    candidates: set[str] = set()
    for kind, url, text in texts:
        local_candidates = extract_candidates(text)
        candidates.update(local_candidates)
        matches = {}
        for kw in KEYWORDS:
            cc = contexts(text, kw)
            if cc:
                matches[kw] = cc
        if matches or local_candidates:
            # collect quoted literals specifically around the Other-box UI label
            near_other = []
            for kw in ("Other boxes", "Other box"):
                for chunk in matches.get(kw, []):
                    quoted = re.findall(r'''["']([^"'\n]{1,100})["']''', chunk)
                    near_other.extend(quoted)
            report["hits"].append({
                "kind": kind,
                "url": url,
                "candidate_literals": sorted(local_candidates),
                "quoted_near_other": sorted(set(near_other)),
                "matches": matches,
            })

    report["candidate_platform_literals"] = sorted(candidates)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("OSN_FRONTEND_PAGES", json.dumps(pages_meta, ensure_ascii=False))
    print("OSN_FRONTEND_PROBE scripts=", len(src_urls))
    print("OSN_FRONTEND_CANDIDATES", json.dumps(report["candidate_platform_literals"], ensure_ascii=False))
    for item in report["hits"]:
        important = {
            k: v for k, v in item["matches"].items()
            if k in {"Other boxes", "Other box", "Android box", "apidata/channels", "tv-schedule-timeline", "boxAndroid", "platform="}
        }
        if not important and not item["candidate_literals"]:
            continue
        print("OSN_FRONTEND_HIT", item["url"])
        if item["candidate_literals"]:
            print("  candidates=", ",".join(item["candidate_literals"]))
        if item["quoted_near_other"]:
            print("  quoted_near_other=", json.dumps(item["quoted_near_other"], ensure_ascii=False))
        for kw, chunks in important.items():
            for chunk in chunks[:4]:
                one = re.sub(r"\s+", " ", chunk)
                print(f"  {kw}: {one[:1400]}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
