#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only 2M provider structure probe. No content publication or files.
Respect robots.txt; log only element counts and structural class hints, never
programme names, programme descriptions, full HTML or user data.
"""
from __future__ import annotations
import json
import re
from urllib import request, error, robotparser
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

URLS = {
  "sudinfo": "https://programmestv.sudinfo.be/programme-tv/chaine/2m-maroc/606",
  "telerama": "https://television.telerama.fr/programme-tv-samedi/2m-maroc",
}
USER_AGENT = "EPGManager-2M-LabProbe/1.0"
MAX_HTML_BYTES = 1000000

def source(url):
    base = urlsplit(url)
    robots = f"{base.scheme}://{base.netloc}/robots.txt"
    rules = robotparser.RobotFileParser()
    rules.set_url(robots)
    try:
        rules.read()
    except Exception:
        return {"state":"ROBOTS_UNAVAILABLE_SKIP"}
    if not rules.can_fetch(USER_AGENT, url):
        return {"state":"ROBOTS_DISALLOW_SKIP"}
    req = request.Request(url,headers={"User-Agent": USER_AGENT,"Accept": "text/html"})
    try:
        with request.urlopen(req,timeout=12) as resp:
            raw=resp.read(MAX_HTML_BYTES+1)
            if len(raw)>MAX_HTML_BYTES:
                return {"state":"TOO_LARGE_SKIP"}
            if resp.url != url:
                return {"state":"REDIRECT_SKIP"}
            html=raw.decode("utf-8","replace")
    except (error.URLError, TimeoutError, OSError) as ex:
        return {"state":"HTTP_UNAVAILABLE","error_type":type(ex).__name__}
    soup=BeautifulSoup(html,"lxml")
    h3s=soup.find_all("h3")
    # Structural labels only, with no programme titles:
    rows=[]
    for el in h3s[:2]:
        seq=[]
        for parent in list(el.parents)[:4]:
            if getattr(parent,"name",None):
                cls=parent.get("class",[])
                safe=[v for v in cls if re.fullmatch(r"[a-zA-Z0-9_-]{1,55}",v)][:4]
                seq.append({"tag":parent.name,"class_tokens":safe,
                            "h3_count":len(parent.find_all("h3")),
                            "anchor_count":len(parent.find_all("a"))})
        rows.append(seq)
    # No source text stored or emitted.
    return {"state":"HTML_RECEIVED","bytes":len(raw),
            "h3_count":len(h3s),"anchors":len(soup.find_all("a")),
            "time_nodes":len(soup.find_all(string=re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$"))),
            "duration_nodes":len(soup.find_all(string=re.compile(r"^\s*(?:(?:\d{1,2}h)?\d{1,2}min|\d{1,2}h\d{1,2})\s*$"))),
            "first_heading_ancestor_shapes":rows}

if __name__=="__main__":
    out={name:source(url) for name,url in URLS.items()}
    out.update({"receiver_modified":False,"feed_published":False,"html_persisted":False,
                "timezone_assumed":False,"republishing_authorized":False})
    print(json.dumps(out,indent=2,sort_keys=True))
