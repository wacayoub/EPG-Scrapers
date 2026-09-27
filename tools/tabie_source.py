#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a direct XMLTV feed from Tabie/Qatar Media Corporation public schedules.

The public page uses /Live/GetSchedule?channelId=<id>&date=YYYY-MM-DD.
We keep QMC/Qatar-family TV services only; third-party carriage on Tabie is not
used to override the broadcaster's own direct source.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import requests

BASE = "https://www.tabie.net"
ENDPOINT = BASE + "/Live/GetSchedule"
QATAR = ZoneInfo("Asia/Qatar")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36 EPGManager-Tabie/1.0"

# Stable EPGManager IDs. Canonical IDs are reused where they already exist.
CHANNELS = {
    23: ("QatarTelevision.qa@SD", "Qatar TV"),
    22: ("QatarTelevision2.qa@SD", "Qatar TV 2"),
    36: ("QatarQuranTV.qa@SD", "Qatar TV Quran"),
    50: ("QatarBusinessChannel.qa@SD", "QBC"),
    32: ("AlkassOne.qa@SD", "Alkass One"),
    12: ("AlRayyanTV.qa@SD", "Al Rayyan TV"),
    11: ("AlRayyanAlQadeem.qa@SD", "Al Rayyan Al Qadeem"),
    34: ("TabieNow.qa", "Tabie Now"),
    35: ("TabieKids.qa", "Tabie Kids"),
}
UNAVAILABLE = {"جدول البرامج غير متاح", "schedule unavailable", "program schedule unavailable"}


def parse_local(value: str | None):
    if not value:
        return None
    raw = str(value).strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=QATAR)
    return dt.astimezone(QATAR)


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S %z")


def fetch_day(session: requests.Session, channel_id: int, date: str, retries: int = 3):
    last = None
    for attempt in range(retries):
        try:
            r = session.get(
                ENDPOINT,
                params={"channelId": channel_id, "date": date},
                timeout=25,
                headers={"Referer": BASE + "/live", "Accept": "application/json,text/plain,*/*"},
            )
            r.raise_for_status()
            data = r.json()
            rows = data.get("programs") if isinstance(data, dict) else None
            return rows if isinstance(rows, list) else []
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt)
    raise RuntimeError(f"Tabie channel={channel_id} date={date}: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--output", default="output/source-build/tabie.raw.xml")
    ap.add_argument("--catalogue", default="output/source-build/tabie.channels.xml")
    ap.add_argument("--report", default="reports/tabie-direct.json")
    args = ap.parse_args()

    days = max(2, min(5, args.days))
    now = datetime.now(QATAR)
    dates = [(now.date() + timedelta(days=i)).isoformat() for i in range(days)]

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "Accept-Language": "ar,en;q=0.8",
        "Cache-Control": "no-cache",
    })

    raw = ET.Element("tv", {
        "generator-info-name": "EPGManager Tabie/QMC direct",
        "generator-info-url": BASE + "/live",
    })
    catalogue = ET.Element("channels")

    for channel_id, (xmltv_id, name) in CHANNELS.items():
        c = ET.SubElement(raw, "channel", {"id": xmltv_id})
        ET.SubElement(c, "display-name", {"lang": "en"}).text = name
        ET.SubElement(c, "url", {"system": "tabie-channel-id"}).text = str(channel_id)

        cc = ET.SubElement(catalogue, "channel", {
            "site": "tabie.net",
            "site_id": str(channel_id),
            "lang": "ar",
            "xmltv_id": xmltv_id,
        })
        cc.text = name

    report = {
        "generated_qatar": now.isoformat(),
        "dates": dates,
        "endpoint": "/Live/GetSchedule",
        "channels": {},
    }
    total = 0

    for channel_id, (xmltv_id, name) in CHANNELS.items():
        seen = set()
        kept = 0
        errors = []
        per_day = {}
        for date in dates:
            try:
                rows = fetch_day(sess, channel_id, date)
            except Exception as exc:
                errors.append(str(exc))
                per_day[date] = {"status": "ERROR", "programmes": 0}
                continue

            day_kept = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").strip()
                if not title or title.casefold() in UNAVAILABLE:
                    continue
                start = parse_local(row.get("startTime"))
                stop = parse_local(row.get("endTime"))
                if not start or not stop or stop <= start:
                    continue

                key = (start.isoformat(), stop.isoformat(), title)
                if key in seen:
                    continue
                seen.add(key)

                p = ET.SubElement(raw, "programme", {
                    "channel": xmltv_id,
                    "start": fmt(start),
                    "stop": fmt(stop),
                })
                ET.SubElement(p, "title", {"lang": "ar"}).text = title
                category = str(row.get("category") or "").strip()
                if category and category.casefold() != "general":
                    ET.SubElement(p, "category", {"lang": "en"}).text = category
                kept += 1
                day_kept += 1
                total += 1
            per_day[date] = {"status": "OK", "programmes": day_kept, "api_rows": len(rows)}

        report["channels"][xmltv_id] = {
            "channel_id": channel_id,
            "name": name,
            "programmes": kept,
            "days": per_day,
            "errors": errors,
            "status": "ACTIVE" if kept else "ZERO_EPG",
        }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.catalogue).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    ET.indent(raw, space="  ")
    ET.indent(catalogue, space="  ")
    Path(args.output).write_bytes(ET.tostring(raw, encoding="utf-8", xml_declaration=True))
    Path(args.catalogue).write_bytes(ET.tostring(catalogue, encoding="utf-8", xml_declaration=True))
    report["programmes"] = total
    report["active_channels"] = sum(1 for x in report["channels"].values() if x["programmes"] > 0)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source": "tabie",
        "channels": len(CHANNELS),
        "active_channels": report["active_channels"],
        "programmes": total,
        "dates": dates,
    }, ensure_ascii=False))
    return 0 if total else 3


if __name__ == "__main__":
    raise SystemExit(main())
