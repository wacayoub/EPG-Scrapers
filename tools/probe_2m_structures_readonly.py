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
    # Telerama programme cards are anchors (not h3). Probe only structure,
    # never print programme titles or other copyrighted source text.
    anchors=soup.find_all("a")
    timed=[]
    for a in anchors:
        txt=" ".join(a.stripped_strings)
        if re.search(r"(?<!\\d)(?:[01]?\\d|2[0-3])[h:][0-5]\\d(?!\\d)",txt):
            timed.append(a)
    timed_shapes=[]
    for el in timed[:4]:
        timed_shapes.append({
            "href_path_present":bool(el.get("href")),
            "class_tokens":[x for x in el.get("class",[]) if re.fullmatch(r"[a-zA-Z0-9_-]{1,55}",x)][:5],
            "span_count":len(el.find_all("span")),
            "li_count":len(el.find_all("li")),
            "time_matches":len(re.findall(r"(?<!\\d)(?:[01]?\\d|2[0-3])[h:][0-5]\\d(?!\\d)", " ".join(el.stripped_strings))),
            "sibling_tag":getattr(el.parent, "name", None),
        })
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
    # Structural telemetry: does Telerama's existing `parse_2m` contract
    # (anchor text containing "21h00" preceded by a title) still hold?
    anchor_times = 0
    anchor_title_before = 0
    anchor_title_after = 0
    hhmm = re.compile(r"(?<!\\d)([01]?\\d|2[0-3])h([0-5]\\d)(?!\\d)")
    for anchor in soup.find_all("a"):
        txt = " ".join(anchor.stripped_strings)
        match = hhmm.search(txt)
        if not match:
            continue
        anchor_times += 1
        if len(txt[:match.start()].strip()) >= 2:
            anchor_title_before += 1
        if len(txt[match.end():].strip()) >= 2:
            anchor_title_after += 1
    html_text = soup.get_text(" ", strip=True)
    anchors = soup.find_all("a")
    # Detect alternate machine-readable structures without emitting their data.
    html_hhmm = len(re.findall(r"(?<!\\d)(?:[01]?\\d|2[0-3])h[0-5]\\d", html, re.I))
    html_colon = len(re.findall(r"(?<!\\d)(?:[01]?\\d|2[0-3]):[0-5]\\d", html))
    html_spaced = len(re.findall(r"(?<!\\d)(?:[01]?\\d|2[0-3])\\s*h\\s*[0-5]\\d", html, re.I))
    scripts = soup.find_all("script")
    script_type_counts = {}
    for sc in scripts:
        t = str(sc.get("type") or "none")
        if not re.fullmatch(r"[a-zA-Z0-9/+.\\-]{1,60}",t):
            t = "other"
        script_type_counts[t] = script_type_counts.get(t,0)+1
    data_json_count = len(soup.find_all("script",type="application/json"))
    time_tags = soup.find_all("time")
    candidate_links=[a for a in anchors if "/tele/" in str(a.get("href") or "") or "/cinema/" in str(a.get("href") or "")]
    candidate_anchor_ancestor_shapes=[]
    for a in candidate_links[:3]:
        row=[]
        for par in list(a.parents)[:3]:
            if getattr(par,"name",None):
                row.append({"tag":par.name,"class_tokens":[t for t in par.get("class",[]) if re.fullmatch(r"[a-zA-Z0-9_-]{1,55}",str(t))][:3]})
        candidate_anchor_ancestor_shapes.append(row)
    # No source text, titles, dates, programme descriptions or HTML emitted.
    return {"state":"HTML_RECEIVED","bytes":len(raw),
            "telerama_contract_metrics":{
                "anchor_time_hhmm":anchor_times,
                "anchor_title_before_time":anchor_title_before,
                "anchor_title_after_time":anchor_title_after,
                "all_page_hhmm_tokens":len(hhmm.findall(html_text)),
                "ld_json_scripts":len(soup.find_all("script",type="application/ld+json")),
                "program_link_hints":sum(1 for a in anchors if "/tele/" in str(a.get("href") or "")),
                "raw_html_hhmm_hits":html_hhmm,
                "raw_html_colon_hits":html_colon,
                "raw_html_spaced_hhmm_hits":html_spaced,
                "body_text_length":len(html_text),
                "body_contains_2m":("2m maroc" in html_text.casefold()),
                "time_tags":len(time_tags),
                "scripts_by_type":script_type_counts,
                "app_json_scripts":data_json_count,
                "program_link_ancestor_shapes":candidate_anchor_ancestor_shapes,
            },
            "h3_count":len(h3s),"anchors":len(anchors),
            "timed_anchor_count":len(timed),
            "first_timed_anchor_shapes":timed_shapes,
            "time_nodes":len(soup.find_all(string=re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$"))),
            "duration_nodes":len(soup.find_all(string=re.compile(r"^\s*(?:(?:\d{1,2}h)?\d{1,2}min|\d{1,2}h\d{1,2})\s*$"))),
            "first_heading_ancestor_shapes":rows}

if __name__=="__main__":
    out={name:source(url) for name,url in URLS.items()}
    out.update({"receiver_modified":False,"feed_published":False,"html_persisted":False,
                "timezone_assumed":False,"republishing_authorized":False})
    print(json.dumps(out,indent=2,sort_keys=True))
