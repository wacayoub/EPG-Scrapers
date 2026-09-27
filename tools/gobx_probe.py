#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public GOBX EPG endpoint discovery.

Discovery only: public pages and public JS assets. No login, DRM, or auth bypass.
"""
from __future__ import annotations
import json, re
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

START = [
    "https://www.gobx.com/en/whats-on",
    "https://www.gobx.com/ar/whats-on",
    "https://www.gobx.com/en/",
    "https://www.gobx.com/ar/",
]

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36"
URL_RE = re.compile(r"""https?://[^"'<>\\\s]+""", re.I)
REL_RE = re.compile(r"""["']([^"']*(?:api|epg|schedule|guide|whats-on|channel|channels|program|programme)[^"']*)["']""", re.I)
HOST_HINT = re.compile(r"(api|epg|schedule|guide|whats-on|channel|program|programme|graphql|gobx|mbc)", re.I)

def fetch(s, url):
    try:
        r = s.get(url, timeout=20, allow_redirects=True)
        return {
            "ok": True, "status": r.status_code, "url": url, "final_url": r.url,
            "content_type": r.headers.get("content-type", ""),
            "text": r.text if len(r.content) < 8000000 else r.text[:8000000],
            "bytes": len(r.content),
        }
    except Exception as e:
        return {"ok": False, "status": "ERROR", "url": url, "error": str(e)[:300], "text": "", "bytes": 0}

def extract_from_text(base, text):
    out = []
    for m in URL_RE.finditer(text):
        u = m.group(0).replace("\\/", "/")
        if HOST_HINT.search(u) and u not in out:
            out.append(u)
        if len(out) >= 400:
            break
    for m in REL_RE.finditer(text):
        v = m.group(1).strip()
        if not v or len(v) > 700:
            continue
        u = urljoin(base, v)
        if u not in out:
            out.append(u)
        if len(out) >= 500:
            break
    return out

def main():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar,en;q=0.8",
        "Referer": "https://www.gobx.com/en/whats-on",
    })
    report = {"pages": [], "js_assets": [], "candidate_endpoints": []}
    js, candidates = set(), set()

    for url in START:
        row = fetch(s, url)
        text = row.pop("text", "")
        page = dict(row)
        if text:
            soup = BeautifulSoup(text, "html.parser")
            page["title"] = soup.title.get_text(" ", strip=True) if soup.title else ""
            page["scripts"] = []
            for tag in soup.find_all("script", src=True):
                src = urljoin(row.get("final_url", url), tag["src"])
                js.add(src)
                page["scripts"].append(src)
            found = extract_from_text(row.get("final_url", url), text)
            candidates.update(found)
            page["candidate_count"] = len(found)
        report["pages"].append(page)

    for src in list(js)[:140]:
        row = fetch(s, src)
        text = row.pop("text", "")
        item = dict(row)
        if text and row.get("status") == 200:
            found = extract_from_text(row.get("final_url", src), text)
            item["candidate_urls"] = found[:220]
            candidates.update(found)
        report["js_assets"].append(item)

    checked = []
    ordered = sorted(candidates, key=lambda u: (
        0 if any(k in u.lower() for k in ("epg","schedule","guide","whats-on","programme")) else 1,
        0 if "api" in u.lower() else 1,
        u
    ))
    for u in ordered:
        if len(checked) >= 180:
            break
        pu = urlparse(u)
        if pu.scheme not in ("http", "https") or not HOST_HINT.search(u):
            continue
        low = u.lower()
        if any(x in low for x in ("login","signin","oauth","token","account","payment","drm","widevine","license")):
            continue
        r = fetch(s, u)
        text = r.pop("text", "")
        checked.append({**r, "sample": re.sub(r"\s+", " ", text[:800]).strip() if text else ""})

    report["candidate_endpoints"] = checked
    Path("reports").mkdir(exist_ok=True)
    Path("reports/gobx-discovery.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    useful = [x for x in checked if isinstance(x.get("status"), int) and x["status"] == 200]
    lines = [
        "# GOBX public EPG endpoint discovery", "",
        f"Pages checked: **{len(report['pages'])}**  ",
        f"Public JS assets inspected: **{len(report['js_assets'])}**  ",
        f"Reachable candidate endpoints: **{len(useful)}**", "",
        "| Endpoint | HTTP | Content-Type | Sample |",
        "|---|---:|---|---|",
    ]
    for x in useful[:60]:
        sample = (x.get("sample") or "").replace("|", "/")[:180]
        lines.append(f'| {x.get("final_url") or x.get("url")} | {x.get("status")} | {x.get("content_type","")} | {sample} |')
    Path("reports/gobx-discovery.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "pages": [{"url": x.get("url"), "status": x.get("status"), "final_url": x.get("final_url"), "scripts": len(x.get("scripts", []))} for x in report["pages"]],
        "js_assets": len(report["js_assets"]),
        "reachable_candidates": len(useful),
        "reachable": [{"url": x.get("final_url") or x.get("url"), "content_type": x.get("content_type"), "sample": x.get("sample","")[:320]} for x in useful[:40]]
    }, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
