#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2M Maroc guide DOM parser, SHADOW ONLY / NO PUBLICATION.

Reads a previously obtained HTML string. Extracts printed date, per-card HH:MM
and programme title. Does NOT infer provider timezone or license to redistribute.
The title/time rows are never written to the GitHub repository or receiver.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
import re
from bs4 import BeautifulSoup

MONTHS=("janvier","février","mars","avril","mai","juin","juillet","août",
        "septembre","octobre","novembre","décembre")
WEEKDAYS=("lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche")
TIME=re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
MAX_HTML_BYTES=850_000
GENERIC=frozenset(("programme", "emission", "émission", "magazine", "film", "série",
                   "documentaire", "à suivre", "2m", "replay"))


def _text(value):
    return " ".join(str(value or "").split())


def _date_verified(soup, day):
    expected="%s %d %s" % (WEEKDAYS[day.weekday()], day.day, MONTHS[day.month-1])
    # The date must belong to the SELECTED dropdown button, not a link
    # offering that day as one of three other navigation options.
    selected=[_text(b.get_text(" ",strip=True)).casefold()
              for b in soup.select("button")]
    return sum(expected in s for s in selected)==1


def parse_html(html, day):
    """Return unqualified wall times and quality counters, never XMLTV."""
    if not isinstance(day,date) or isinstance(day,datetime):
        raise ValueError("explicit broadcast date required")
    if not isinstance(html,str) or len(html.encode("utf-8"))>MAX_HTML_BYTES:
        raise ValueError("untrusted/oversized provider payload")
    soup=BeautifulSoup(html,"lxml")
    headings=[_text(h.get_text(" ",strip=True)).casefold() for h in soup.find_all(["h1","h2"])]
    if "grille de 2m" not in headings:
        raise ValueError("not 2M guide page")
    if not _date_verified(soup,day):
        raise ValueError("selected date does not match requested date")
    cards=soup.select("div.program-item")
    if not cards:
        raise ValueError("no structured programme cards")
    rows=[]
    seen=set()
    last_clock=None
    rollover=False
    counters={"cards_seen":len(cards),"invalid_cards":0,
              "duplicate_slots":0,"near_duplicate_titles":0,
              "out_of_order":0,"generic_titles":0}
    for card in cards[:170]:
        h=card.find("h6")
        title=_text(h.get_text(" ",strip=True)) if h else ""
        if not (3<=len(title)<=140):
            counters["invalid_cards"]+=1
            continue
        ts=[_text(s) for s in card.stripped_strings]
        times=[s for s in ts if TIME.fullmatch(s)]
        if len(times)!=1:
            counters["invalid_cards"]+=1
            continue
        clock=times[0]
        hh,mm=map(int,clock.split(":"))
        tick=hh*60+mm
        if last_clock is not None and tick<last_clock:
            if not rollover and last_clock>=18*60 and tick<6*60:
                rollover=True
            else:
                counters["out_of_order"]+=1
                continue
        last_clock=tick
        broadcast=day+timedelta(days=1 if rollover else 0)
        start=datetime.combine(broadcast,datetime.min.time())+timedelta(minutes=tick)
        key=start.isoformat(timespec="minutes")
        if key in seen:
            counters["duplicate_slots"]+=1
            continue
        seen.add(key)
        if title.casefold() in GENERIC:
            counters["generic_titles"]+=1
            continue
        if rows and rows[-1]["title"].casefold()==title.casefold() and \
                (start-datetime.fromisoformat(rows[-1]["wall_time"])).total_seconds()<10*60:
            # A near-duplicate is often a syndicated/rescheduled repeat;
            # flag it without guessing the correct real broadcast slot.
            counters["near_duplicate_titles"]+=1
            continue
        rows.append({"channel_id":"2M","wall_time":key,"title":title,
                     "source":"communesmaroc-2m"})
    counters["candidate_count"]=len(rows)
    counters["page_date_verified"]=True
    counters["timezone_verified"]=False
    counters["reuse_permission_verified"]=False
    counters["publication_authorized"]=False
    counters["ready_for_xmltv"]=False
    return {"rows":rows,"quality":counters}


def quality_summary(parsed):
    """Safe CI output: aggregate metrics only, no provider programme names."""
    return dict(parsed["quality"])
