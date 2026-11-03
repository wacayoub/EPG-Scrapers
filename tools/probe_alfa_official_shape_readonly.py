#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot official Alfa guide structure discovery; does NOT publish EPG.

Respect robots, no cross-origin fetches, never reveal programme titles or
client tokens. Only provider HTML structural measurements and endpoint hints.
"""
import json,re
from urllib import request,robotparser,error
from urllib.parse import urljoin,urlsplit
from html.parser import HTMLParser
from collections import Counter

BASE="https://alfatv.com"
GUIDE=BASE+"/en/tv-guide"
UA="EPGManager-Alfa-guide-research/1.0"
MAX_HTML=1_400_000
MAX_JS=1_400_000

class Scan(HTMLParser):
    def __init__(self):
        super().__init__();self.scripts=[];self.tags=Counter()
    def handle_starttag(self, tag, attrs):
        self.tags[tag]+=1
        if tag=="script":
            d=dict(attrs);src=d.get("src")
            if src:self.scripts.append(src)

def fetch(url,robots,maxbytes):
    if not robots.can_fetch(UA,url):return None,"ROBOTS_DISALLOW"
    u=urlsplit(url)
    if u.scheme!="https" or u.hostname!="alfatv.com":return None,"WRONG_ORIGIN"
    opener=request.build_opener(request.ProxyHandler({}),NoRedirect())
    req=request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,application/javascript"})
    try:
        with opener.open(req,timeout=18) as r:
            if r.url!=url:return None,"REDIRECT_DISALLOWED"
            b=r.read(maxbytes+1)
            if len(b)>maxbytes:return None,"OVERSIZE"
            return b,"OK"
    except (OSError,error.URLError,TimeoutError) as ex:
        return None,type(ex).__name__

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):return None

def api_hints(js):
    text=js.decode("utf8","ignore")
    # Never report script raw content: only known public endpoint fragments.
    rules={
      "graphql": r"graphql",
      "api_route":r"\/api\/(?:[a-z][a-z0-9_/-]{2,45})",
      "schedule":r"schedule|epg|tvguide",
      "program":r"programme|programs|tv-guide",
      "content_api":r"contentful|strapi|wp-json",
      "next_data":r"__NEXT_DATA__|__NUXT__|_next\/static",
    }
    out={}
    for key,pattern in rules.items():
        out[key]=min(500,len(re.findall(pattern,text,re.I)))
    return out

def probe():
    rr=robotparser.RobotFileParser();rr.set_url(BASE+"/robots.txt")
    try:rr.read()
    except (OSError,error.URLError):
        return {"state":"ROBOTS_UNAVAILABLE","published":False}
    html,status=fetch(GUIDE,rr,MAX_HTML)
    if html is None:return {"state":status,"published":False}
    txt=html.decode("utf8","replace")
    page=Scan();page.feed(txt)
    report={"state":"HTML_RECEIVED","bytes":len(html),
       "script_count":len(page.scripts),"tag_counts":{z:page.tags[z] for z in ("script","time","article","table","tr","li")},
       "page_markers":api_hints(html),"firstparty_js_files_scanned":0,
       "js_markers":[],"published":False,"programme_data_saved":False}
    selected=[]
    for script in page.scripts:
        url=urljoin(GUIDE,script)
        if urlsplit(url).hostname=="alfatv.com" and urlsplit(url).path.endswith(".js"):
            if url not in selected:selected.append(url)
    for url in selected[:4]:
        data,state=fetch(url,rr,MAX_JS)
        if data is None:
            report["js_markers"].append({"state":state})
        else:
            report["js_markers"].append({"state":"SCANNED","bytes":len(data),"hints":api_hints(data)})
            report["firstparty_js_files_scanned"]+=1
    return report

if __name__=="__main__":
    print(json.dumps(probe(),indent=2,sort_keys=True))
