#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Official Alfa TV-guide source shape / robots metadata only, NO programme export.

This is an assessment of a user-visible website, not a licence to re-publish
broadcast schedule data. Does not follow external redirects or fetch API keys.
"""
from __future__ import annotations
from html.parser import HTMLParser
from urllib import robotparser,request,error
from urllib.parse import urlsplit
import json
import re

URL="https://alfatv.com/ar/tv-guide"
ROBOTS="https://alfatv.com/robots.txt"
UA="EPGManager-Source-Assessment/1.0"
MAX_HTML=1200000
TIME = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3])[:h][0-5]\d(?!\d)")

class Shape(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags={}
        self.script_sources=0
        self.json_blocks=0
        self.time_attributes=0
        self.channel_refs=0
        self.guide_attrs=0
    def handle_starttag(self,tag,attrs):
        self.tags[tag]=self.tags.get(tag,0)+1
        d=dict(attrs)
        if tag=="script" and d.get("src"):
            self.script_sources+=1
        if tag=="script" and ("json" in (d.get("type") or "").lower()):
            self.json_blocks+=1
        if any(TIME.search(v or "") for _,v in attrs):
            self.time_attributes+=1
        if any("channel" in k.lower() for k,_ in attrs):
            self.channel_refs+=1
        if any(any(w in k.lower() for w in ("schedule","programme","program","guide")) for k,_ in attrs):
            self.guide_attrs+=1

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

def probe():
    report={"source":"alfatv.com","kind":"OFFICIAL_GUIDE_SHAPE_ONLY",
            "programmes_republished":False,"receiver_modified":False,
            "guide_times_and_timezone_verified":False,
            "redistribution_permission_verified":False}
    rp=robotparser.RobotFileParser()
    rp.set_url(ROBOTS)
    try:
        rp.read()
        # Missing/unparseable robots policy: fail closed.
        if not rp.can_fetch(UA,URL):
            report["status"]="ROBOTS_DENY_OR_UNAVAILABLE"
            return report
    except Exception:
        report["status"]="ROBOTS_UNAVAILABLE"
        return report
    try:
        opener=request.build_opener(request.ProxyHandler({}),NoRedirect)
        req=request.Request(URL,headers={"User-Agent":UA,"Accept":"text/html"})
        with opener.open(req,timeout=15) as response:
            if response.url!=URL or "html" not in (response.headers.get("Content-Type") or "").lower():
                raise ValueError("unexpected response")
            raw=response.read(MAX_HTML+1)
        if len(raw)>MAX_HTML:
            report["status"]="OVERSIZED_SKIP"
            return report
        text=raw.decode("utf-8","replace")
        html=Shape()
        html.feed(text)
        report.update({"status":"HTML_RECEIVED","bytes":len(raw),
                       "script_sources":html.script_sources,
                       "json_scripts":html.json_blocks,
                       "datetime_attributes":html.time_attributes,
                       "channel_attributes":html.channel_refs,
                       "guide_attributes":html.guide_attrs,
                       "html_time_token_count":len(TIME.findall(text)),
                       "has_next_data":'__NEXT_DATA__' in text,
                       "has_nuxt_data":'__NUXT__' in text,
                       "dom_sections":sum(html.tags.get(tag,0) for tag in ("article","section")),
                       "requires_independent_programme_date_validation":True})
    except (OSError,error.URLError,TimeoutError,ValueError) as e:
        report.update({"status":"UNAVAILABLE","error_type":type(e).__name__})
    return report

if __name__=="__main__":
    print(json.dumps(probe(),sort_keys=True,ensure_ascii=False,indent=2))
