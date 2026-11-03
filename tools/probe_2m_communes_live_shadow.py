#!/usr/bin/env python3
"""One-shot 2M Morocco local source probe. No source data publication.

Respects provider robots.txt. Downloads at most 3 dated guide pages, logs only
counts/quality and confirms date alignment. It does not run the Enigma2 plugin.
"""
from __future__ import annotations
from datetime import date,timedelta
from urllib import request,robotparser,error
from urllib.parse import urlencode
import json
from communesmaroc_2m_shadow import parse_html,quality_summary,MAX_HTML_BYTES

BASE="https://www.communesmaroc.com"
PATH="/fr/tv-programs/2m"
UA="EPGManager-2M-Shadow/1.0"

def main():
    robots=robotparser.RobotFileParser()
    robots.set_url(BASE+"/robots.txt")
    robots.read()
    day=date.today()
    reports=[]
    for offset in range(3):
        d=day+timedelta(days=offset)
        url=BASE+PATH+"?"+urlencode({"dt":d.isoformat()})
        if not robots.can_fetch(UA,url):
            reports.append({"day_offset":offset,"status":"ROBOTS_DISALLOW"})
            break
        req=request.Request(url,headers={"User-Agent":UA,"Accept":"text/html"})
        try:
            with request.urlopen(req,timeout=12) as response:
                if response.url != url:
                    raise ValueError("redirected page; refuse")
                raw=response.read(MAX_HTML_BYTES+1)
            if len(raw)>MAX_HTML_BYTES:
                raise ValueError("oversized source HTML")
            parsed=parse_html(raw.decode("utf-8"),d)
            summary=quality_summary(parsed)
            summary.update({"day_offset":offset,"status":"SHADOW_PARSED"})
            reports.append(summary)
        except (ValueError,UnicodeError,error.URLError,TimeoutError,OSError) as exc:
            reports.append({"day_offset":offset,"status":"FAIL_CLOSED",
                            "error_type":type(exc).__name__})
    result={"audit":"2M Morocco external source shadow","published":False,
            "receiver_modified":False,"source_timezone_verified":False,
            "reuse_permission_verified":False,"reports":reports}
    print(json.dumps(result,indent=2,ensure_ascii=False,sort_keys=True))
    # Failure is informative only; deployment remains disallowed regardless.
    return 0 if all(r.get("status")=="SHADOW_PARSED" for r in reports) and len(reports)==3 else 2

if __name__=="__main__":
    raise SystemExit(main())
