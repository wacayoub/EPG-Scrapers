#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2M/Sudinfo programme-guide SHADOW parser (never publishes).

Usage: python tools/sudinfo_2m_shadow.py --html /path/to/saved.html --date 2026-10-17
Only programme title, printed time and *explicit* duration are interpreted.
The upstream site's timezone and reuse permission remain UNVERIFIED, so this
module MUST NOT emit XMLTV, change a mapping, or write a production feed.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup

TIME = re.compile(r"(?<!\d)([01]\d|2[0-3]):([0-5]\d)(?!\d)")
DURATION = re.compile(r"(?<!\d)(?:(\d{1,2})\s*h\s*(\d{1,2})?|(\d{1,3})\s*min)(?![a-z])", re.I)
MONTHS = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]
WEEKDAYS = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
GENERIC = {"film", "documentaire", "programme", "émission", "divertissement", "série"}
MAX_BYTES = 1000000


def clean(s):
    return " ".join(str(s or "").split()).strip()


def page_date_verified(html, day, route):
    """A weekday permalink can prove its *displayed* day/month only.

    Today's relative route has no date in the title, so it remains unverified
    until independent site date evidence is available.
    """
    soup = BeautifulSoup(html, "lxml")
    header = clean((soup.title.get_text(" ", strip=True) if soup.title else "") +
                   " " + (soup.h1.get_text(" ", strip=True) if soup.h1 else ""))
    if route in ("aujourdhui", "demain"):
        return False
    expected = WEEKDAYS[day.weekday()]
    if route != expected and route != expected + "prochain":
        return False
    # Require a date in the page header, not a link to another navigation day.
    return bool(re.search(r"\b" + expected + r"\s+" + str(day.day) +
                          r"\s+" + MONTHS[day.month - 1] + r"\b", header, re.I))


def _card(heading):
    """Conservative single-event ancestry search; never parse nav/footer."""
    for parent in list(heading.parents)[:6]:
        if getattr(parent, "name", "") in ("body", "main", "html", "section"):
            break
        if len(parent.find_all("h3")) != 1:
            continue
        txt = clean(parent.get_text(" ", strip=True))
        title = clean(heading.get_text(" ", strip=True))
        if not title or not (5 <= len(txt) <= 420):
            continue
        before, sep, after = txt.partition(title)
        if not sep:
            continue
        times = TIME.findall(before)
        duration = DURATION.search(after)
        if not times or not duration:
            continue
        hh, mm = map(int, times[-1])
        hours = int(duration.group(1) or 0)
        mins = int(duration.group(2) or 0) if duration.group(1) else int(duration.group(3))
        length = 60 * hours + mins
        if not 1 <= length <= 240:
            continue
        return hh, mm, length
    return None


def parse_shadow(html, broadcast_day, route="aujourdhui"):
    """Return human-readable candidate rows, NEVER time-zone-qualified EPG."""
    if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_BYTES:
        raise ValueError("untrusted/oversized input")
    if not isinstance(broadcast_day, date):
        raise ValueError("date required")
    soup = BeautifulSoup(html, "lxml")
    title = clean(soup.h1.get_text(" ", strip=True)) if soup.h1 else ""
    if "2m" not in title.casefold() or "maroc" not in title.casefold():
        raise ValueError("wrong channel page")
    verified_date = page_date_verified(html, broadcast_day, route)
    if route not in ("aujourdhui", "demain") and not verified_date:
        raise ValueError("page date not verified; possibly stale weekday URL")
    candidates = []
    seen = set()
    for h in soup.find_all("h3"):
        if h.find_parent(["header", "footer", "nav"]):
            continue
        title = clean(h.get_text(" ", strip=True))
        if not 3 <= len(title) <= 120:
            continue
        details = _card(h)
        if not details:
            continue
        hour, minute, duration = details
        sig = (hour, minute, title.casefold())
        if sig in seen:
            continue
        seen.add(sig)
        candidates.append((hour, minute, duration, title))
    # Programmes are presented in broadcast order: 06:00 -> 23:xx -> 00:xx
    # of the following day. Never assign early-morning programmes backwards.
    day_offset, last = 0, None
    rows = []
    for hour, minute, duration, name in candidates:
        clock = hour * 60 + minute
        if last is not None and clock < last:
            if last >= 18 * 60 and clock <= 6 * 60 and day_offset == 0:
                day_offset = 1
            else:
                raise ValueError("out-of-order or duplicate broadcast times")
        last = clock
        local = datetime.combine(broadcast_day + timedelta(days=day_offset), datetime.min.time())
        local += timedelta(minutes=clock)
        rows.append({"wall_time": local.isoformat(timespec="minutes"),
                     "duration_minutes": duration,
                     "title": name,
                     "title_quality": "GENERIC_REVIEW" if name.casefold() in GENERIC else "CANDIDATE",
                     "source": "sudinfo-2m-606"})
    return {"channel_id": "2M", "source": "sudinfo-2m-606",
            "publication_authorized": False, "xmltv_ready": False,
            "source_timezone_verified": False,
            "reuse_permission_verified": False,
            "page_date_verified": verified_date, "candidate_count": len(rows),
            "non_generic_count": sum(row["title_quality"] == "CANDIDATE" for row in rows),
            "rows": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--html", required=True, help="Local, previously saved HTML")
    ap.add_argument("--date", required=True, help="Expected TV page date YYYY-MM-DD")
    ap.add_argument("--route", default="aujourdhui",
                    choices=["aujourdhui","demain"] + WEEKDAYS + [x+"prochain" for x in WEEKDAYS])
    args = ap.parse_args()
    result = parse_shadow(Path(args.html).read_text(encoding="utf-8"),
                          date.fromisoformat(args.date), args.route)
    # The shadow probe prints only counts, not the site's whole copyrighted guide.
    result.pop("rows")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
