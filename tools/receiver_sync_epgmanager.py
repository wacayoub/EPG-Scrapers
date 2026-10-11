#!/usr/bin/env python3
"""Safely refresh EPGManager local XMLTV files from EPG-Scrapers GitHub.

Does not change mappings, settings, scheduler, rytec.channels.xml or
*.xml.lastgood backups. Expired or invalid remote feeds are never installed.
"""
import argparse
import gzip
import io
import os
import re
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

BASE_URL = "https://raw.githubusercontent.com/wacayoub/EPG-Scrapers/main/feeds"
SOURCES = (
    "morocco", "bein", "osn", "shahid", "elcinema", "rotana", "dubaiplus",
    "sport24", "stctv", "aljazeera", "alkass", "starzplay", "tabie", "tunisiatv"
)
MAX_GZIP = 12 * 1024 * 1024
MAX_XML = 80 * 1024 * 1024


def xmltv_date(s):
    m = re.match(r"^(\d{14})(?:\s*([+-])(\d{2}):?(\d{2}))?", s or "")
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    off = timedelta()
    if m.group(2):
        off = timedelta(hours=int(m.group(3)), minutes=int(m.group(4)))
        if m.group(2) == "-":
            off = -off
    return dt.replace(tzinfo=timezone(off)).astimezone(timezone.utc)


def inspect_xml(data, now):
    channels = count = future = 0
    latest = None
    root = None
    for event, node in ET.iterparse(io.BytesIO(data), events=("start", "end")):
        if root is None and event == "start":
            root = node.tag.rsplit("}", 1)[-1]
        if event != "end":
            continue
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "channel":
            channels += 1
        elif tag == "programme":
            count += 1
            end = xmltv_date(node.get("stop") or node.get("start"))
            if end:
                if latest is None or end > latest:
                    latest = end
                if end > now:
                    future += 1
        node.clear()
    if root != "tv":
        raise ValueError("Not an XMLTV document")
    return channels, count, future, latest


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "EPGManager-Recovery/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        packed = resp.read(MAX_GZIP + 1)
    if not packed or len(packed) > MAX_GZIP:
        raise ValueError("Missing or oversized gzip file")
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as f:
        data = f.read(MAX_XML + 1)
    if not data or len(data) > MAX_XML:
        raise ValueError("Missing or oversized XML")
    return data


def replace_atomic(path, data):
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".epg-recovery-",
                                         suffix=".tmp", dir=str(path.parent),
                                         delete=False) as f:
            tmp = f.name
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, str(path))
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def main():
    p = argparse.ArgumentParser(description="Recover EPGManager source XMLs")
    p.add_argument("--dir", default="/etc/epgmanager_epg")
    p.add_argument("--base-url", default=BASE_URL)
    p.add_argument("--only", help="Comma-separated source names")
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args()
    directory = Path(args.dir)
    if not directory.is_dir():
        p.error("Source directory not found: %s" % directory)
    selected = [s.strip() for s in args.only.split(",")] if args.only else list(SOURCES)
    if any(s not in SOURCES for s in selected):
        p.error("Unknown source in --only")
    now = datetime.now(timezone.utc)
    updated = skipped = failed = 0
    print("EPGManager recovery | %s UTC | %s" %
          (now.strftime("%Y-%m-%d %H:%M"), directory), flush=True)
    for source in selected:
        dst = directory / (source + ".xml")
        if not dst.is_file():
            print("SKIP %-12s Local XML not found" % source, flush=True)
            skipped += 1
            continue
        try:
            data = download(args.base_url.rstrip("/") + "/" + source + ".xml.gz")
            channels, count, future, end = inspect_xml(data, now)
            last = end.strftime("%d/%m %H:%M UTC") if end else "NONE"
            if channels < 1 or count < 5 or future < 5 or not end or end < now + timedelta(hours=6):
                print("SKIP %-12s %d channels | %d programmes | %d future | ends %s (stale remote)" %
                      (source, channels, count, future, last), flush=True)
                skipped += 1
                continue
            if not args.check_only:
                replace_atomic(dst, data)
            print("%-4s %-12s %d channels | %d programmes | %d future | ends %s" %
                  ("TEST" if args.check_only else "OK", source, channels, count, future, last), flush=True)
            updated += 1
        except Exception as exc:
            print("FAIL %-12s %s" % (source, exc), flush=True)
            failed += 1
    print("RESULT: %d %s; %d skipped; %d errors; mappings and lastgood untouched." %
          (updated, "valid" if args.check_only else "updated", skipped, failed), flush=True)
    return 0 if updated else 1


if __name__ == "__main__":
    raise SystemExit(main())
