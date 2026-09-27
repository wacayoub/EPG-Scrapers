#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build XMLTV from the public GOBX TV Guide API.

The endpoint definitions are taken from the public GOBX Android application:
  https://fe-api.prod.gobx.com/api/v2/gracenote-fe-api/

This adapter does not bypass Cloudflare, authentication, geo controls or DRM.
If the public API is challenged/blocked, it exits non-zero and writes a report;
the refresh workflow then preserves the last-known-good feed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import html as html_mod
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import requests

BASE_URL = "https://fe-api.prod.gobx.com/api/v2/gracenote-fe-api/"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
NONWORD_RE = re.compile(r"[^a-z0-9]+")
TITLE_KEYS = (
    "programmeName", "programName", "programmeTitle", "programTitle",
    "eventName", "title", "name", "displayTitle", "display_name",
)
DESC_KEYS = (
    "description", "programmeDescription", "programDescription", "synopsis",
    "shortDescription", "short_description", "summary", "overview",
)
START_KEYS = (
    "startTime", "start_time", "start", "startsAt", "startDate",
    "start_date", "eventStart", "broadcastStart", "startDateTime",
)
STOP_KEYS = (
    "endTime", "end_time", "stop", "end", "endsAt", "endDate",
    "end_date", "eventEnd", "broadcastEnd", "endDateTime",
)
CHANNEL_NAME_KEYS = (
    "channelDisplayNameFromGraceNote", "channelDisplayName", "channelName",
    "channel_name", "stationName", "networkName", "serviceName",
)
CHANNEL_ID_KEYS = (
    "channelId", "channelID", "channel_id", "stationId", "networkId",
    "serviceId", "lcn", "channelNumber",
)
CHANNEL_CONTAINER_KEYS = (
    "channel", "station", "network", "service", "channelDetails",
    "channelData", "channelInfo",
)


def norm_name(value: str) -> str:
    text = html_mod.unescape(value or "").casefold().replace("&", " and ")
    return " ".join(NONWORD_RE.sub(" ", text).split())


def read_id_index(path: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path or not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "|" not in line:
            continue
        cid, name = line.split("|", 1)
        cid, name = cid.strip(), name.strip()
        if cid and name:
            out.setdefault(norm_name(name), cid)
    return out


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("text", "value", "name", "title", "ar", "en"):
            if key in value and value[key] not in (None, ""):
                return scalar(value[key])
    return ""


def first_value(obj: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = obj.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        if x > 10_000_000_000:
            x /= 1000.0
        try:
            return datetime.fromtimestamp(x, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        try:
            return parse_dt(float(text))
        except ValueError:
            return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def find_channel_context(obj: dict[str, Any], inherited: dict[str, str]) -> dict[str, str]:
    ctx = dict(inherited)

    for key in CHANNEL_CONTAINER_KEYS:
        nested = obj.get(key)
        if isinstance(nested, dict):
            name = scalar(first_value(nested, ("displayName", "display_name", "name", "title") + CHANNEL_NAME_KEYS))
            sid = scalar(first_value(nested, ("id", "sourceId", "source_id") + CHANNEL_ID_KEYS))
            if name:
                ctx["name"] = name
            if sid:
                ctx["source_id"] = sid

    name = scalar(first_value(obj, CHANNEL_NAME_KEYS))
    sid = scalar(first_value(obj, CHANNEL_ID_KEYS))
    if name:
        ctx["name"] = name
    if sid:
        ctx["source_id"] = sid

    # Some GOBX channel containers expose generic name/id plus channel-ish fields.
    keys_lower = {str(k).casefold() for k in obj}
    looks_channel = any("channel" in k for k in keys_lower) or any(k in keys_lower for k in ("lcn", "servicename"))
    if looks_channel:
        generic_name = scalar(first_value(obj, ("displayName", "display_name", "name")))
        generic_id = scalar(first_value(obj, ("id", "sourceId", "source_id")))
        if generic_name and not ctx.get("name"):
            ctx["name"] = generic_name
        if generic_id and not ctx.get("source_id"):
            ctx["source_id"] = generic_id
    return ctx


def collect_events(obj: Any, inherited: dict[str, str] | None = None) -> list[dict[str, Any]]:
    inherited = inherited or {}
    found: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        ctx = find_channel_context(obj, inherited)
        title = scalar(first_value(obj, TITLE_KEYS))
        start = parse_dt(first_value(obj, START_KEYS))
        stop = parse_dt(first_value(obj, STOP_KEYS))

        # Treat a node as a programme only when it has a real start instant,
        # a title, and a channel identity inherited from the enclosing channel.
        if title and start and (ctx.get("name") or ctx.get("source_id")):
            if stop is None or stop <= start:
                duration = first_value(
                    obj,
                    ("duration", "durationSeconds", "duration_seconds",
                     "durationMinutes", "duration_minutes"),
                )
                try:
                    n = float(duration)
                    if "minute" in " ".join(map(str, obj.keys())).casefold() or n < 600:
                        stop = start + timedelta(minutes=n)
                    else:
                        stop = start + timedelta(seconds=n)
                except (TypeError, ValueError):
                    stop = None
            found.append(
                {
                    "source_id": ctx.get("source_id", ""),
                    "channel_name": ctx.get("name", ""),
                    "title": title,
                    "description": scalar(first_value(obj, DESC_KEYS)),
                    "start": start,
                    "stop": stop,
                    "programme_id": scalar(first_value(obj, ("programmeId", "programId", "eventId", "id"))),
                }
            )

        for value in obj.values():
            if isinstance(value, (dict, list)):
                found.extend(collect_events(value, ctx))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(collect_events(value, inherited))
    return found


def get_int_recursive(obj: Any, names: Iterable[str]) -> int | None:
    wanted = {x.casefold() for x in names}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).casefold() in wanted:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
        for value in obj.values():
            if isinstance(value, (dict, list)):
                got = get_int_recursive(value, names)
                if got is not None:
                    return got
    elif isinstance(obj, list):
        for value in obj:
            got = get_int_recursive(value, names)
            if got is not None:
                return got
    return None


def make_channel_id(name: str, source_id: str, index: dict[str, str]) -> str:
    normalized = norm_name(name)
    if normalized and normalized in index:
        return index[normalized]

    aliases = {
        "mbc 1": "MBC1.sa@SD",
        "mbc1": "MBC1.sa@SD",
        "mbc 2": "MBC2.sa@SD",
        "mbc2": "MBC2.sa@SD",
        "mbc 3": "MBC3.sa@SD",
        "mbc3": "MBC3.sa@SD",
        "mbc 4": "MBC4.sa@SD",
        "mbc4": "MBC4.sa@SD",
        "mbc 5": "MBC5.ma@SD",
        "mbc5": "MBC5.ma@SD",
        "mbc action": "MBCAction.sa@SD",
        "mbc max": "MBCMax.sa@SD",
        "mbc drama": "MBCDrama.sa@SD",
        "mbc masr": "MBCMasr.eg@SD",
        "mbc masr 2": "MBCMasr2.eg@SD",
        "al arabiya": "AlArabiya.ae@SD",
        "al hadath": "AlHadath.ae@SD",
    }
    if normalized in aliases:
        return aliases[normalized]

    stable = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_id or "").strip("-")
    if stable:
        return f"gobx.{stable}"
    digest = hashlib.sha1((normalized or name or "unknown").encode("utf-8")).hexdigest()[:14]
    return f"gobx.{digest}"


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def build_xml(
    events: list[dict[str, Any]],
    id_index: dict[str, str],
    hours: int,
    lang: str,
) -> tuple[ET.Element, dict[str, Any]]:
    now = datetime.now(timezone.utc)
    max_start = now + timedelta(hours=max(1, hours))
    min_stop = now - timedelta(hours=2)

    channels: dict[str, dict[str, str]] = {}
    by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()

    for event in events:
        start = event.get("start")
        if not isinstance(start, datetime) or start >= max_start:
            continue
        stop = event.get("stop")
        if isinstance(stop, datetime) and stop <= min_stop:
            continue
        cid = make_channel_id(
            event.get("channel_name", ""),
            event.get("source_id", ""),
            id_index,
        )
        key = (cid, fmt_dt(start), event.get("programme_id") or event.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        channels.setdefault(
            cid,
            {
                "name": event.get("channel_name") or cid,
                "source_id": event.get("source_id", ""),
            },
        )
        by_channel[cid].append({**event, "cid": cid})

    # Fill missing end times from the next programme only; otherwise use a
    # conservative one-hour end so XMLTV remains valid.
    for rows in by_channel.values():
        rows.sort(key=lambda x: x["start"])
        for i, event in enumerate(rows):
            stop = event.get("stop")
            if not isinstance(stop, datetime) or stop <= event["start"]:
                nxt = rows[i + 1]["start"] if i + 1 < len(rows) else None
                event["stop"] = (
                    nxt if isinstance(nxt, datetime) and nxt > event["start"]
                    else event["start"] + timedelta(hours=1)
                )

    root = ET.Element(
        "tv",
        {
            "generator-info-name": "EPGManager GOBX public TV Guide",
            "generator-info-url": "https://www.gobx.com/",
        },
    )
    for cid in sorted(channels, key=str.casefold):
        node = ET.SubElement(root, "channel", {"id": cid})
        ET.SubElement(node, "display-name", {"lang": lang}).text = channels[cid]["name"]
        if channels[cid]["source_id"]:
            ET.SubElement(node, "url", {"system": "gobx-id"}).text = channels[cid]["source_id"]

    count = 0
    for cid in sorted(by_channel, key=str.casefold):
        for event in by_channel[cid]:
            p = ET.SubElement(
                root,
                "programme",
                {
                    "channel": cid,
                    "start": fmt_dt(event["start"]),
                    "stop": fmt_dt(event["stop"]),
                },
            )
            ET.SubElement(p, "title", {"lang": lang}).text = event["title"]
            if event.get("description"):
                ET.SubElement(p, "desc", {"lang": lang}).text = event["description"]
            count += 1

    return root, {"channels": len(channels), "programmes": count}


class GobxClient:
    def __init__(self, timeout: int, delay: float):
        self.timeout = timeout
        self.delay = max(0.0, delay)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "ar,en;q=0.8",
                "Referer": "https://www.gobx.com/",
            }
        )
        self.requests: list[dict[str, Any]] = []

    def get(self, path: str, params: dict[str, Any]) -> tuple[int, Any, str]:
        url = BASE_URL + path.lstrip("/")
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            self.requests.append({"path": path, "status": 0, "error": str(exc)})
            return 0, None, str(exc)

        ctype = response.headers.get("content-type", "")
        challenge = (
            response.status_code in {401, 403, 451}
            or "text/html" in ctype.casefold()
            or "just a moment" in response.text[:1500].casefold()
            or "challenges.cloudflare.com" in response.text[:3000].casefold()
        )
        row = {
            "path": path,
            "status": response.status_code,
            "content_type": ctype,
            "bytes": len(response.content),
            "challenge_or_block": challenge,
        }
        self.requests.append(row)

        if challenge:
            return response.status_code, None, "cloudflare_or_access_block"
        try:
            data = response.json()
        except ValueError:
            return response.status_code, None, "non_json_response"
        if self.delay:
            time.sleep(self.delay)
        return response.status_code, data, ""


def select_language(client: GobxClient, candidates: list[str]) -> tuple[str, Any, str]:
    last_error = ""
    for value in candidates:
        status, data, error = client.get("now-showing", {"contentLanguage": value})
        if error == "cloudflare_or_access_block":
            # Do not hammer Cloudflare with alternate spellings when the request
            # was stopped before it reached the application.
            return "", None, error
        if status == 200 and isinstance(data, (dict, list)):
            return value, data, ""
        last_error = error or f"http_{status}"
    return "", None, last_error or "no_language_variant_accepted"


def fetch_tv_guide(
    client: GobxClient,
    language: str,
    hours: int,
    page_size: int,
    max_pages: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = datetime.now(timezone.utc)
    start_ms = int((now - timedelta(hours=2)).timestamp() * 1000)
    end_ms = int((now + timedelta(hours=max(1, hours))).timestamp() * 1000)

    events: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    page = 0
    expected_pages: int | None = None

    while page < max_pages and (expected_pages is None or page < expected_pages):
        params = {
            "pageNumber": page,
            "pageSize": page_size,
            "startTime": start_ms,
            "endTime": end_ms,
            "contentLanguage": language,
            "status": "PUBLISHED",
        }
        status, data, error = client.get("channel/filter", params)
        page_info: dict[str, Any] = {"page": page, "status": status, "error": error}
        if error or status != 200 or not isinstance(data, (dict, list)):
            pages.append(page_info)
            break

        page_events = collect_events(data)
        page_info["events"] = len(page_events)
        events.extend(page_events)

        current = get_int_recursive(data, ("currentPage", "current_page", "pageNumber", "page"))
        total = get_int_recursive(data, ("totalPages", "total_pages", "pageCount", "numberOfPages"))
        page_info["reported_current_page"] = current
        page_info["reported_total_pages"] = total
        pages.append(page_info)

        if total is not None:
            # GOBX app compares currentPage < totalPages - 1, so totalPages is a
            # count and currentPage is zero-based.
            expected_pages = max(1, min(max_pages, total))
        if not page_events and total is None:
            break
        page += 1

    return events, pages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--id-index", default="feeds/mena.txt")
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--page-size", type=int, default=50)
    ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument(
        "--languages",
        default="ARABIC,Arabic,ar,ENGLISH,English,en",
        help="Comma-separated contentLanguage candidates",
    )
    args = ap.parse_args()

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client = GobxClient(args.timeout, args.delay)
    languages = [x.strip() for x in args.languages.split(",") if x.strip()]
    chosen, now_showing, error = select_language(client, languages)

    events: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    if chosen:
        # now-showing is useful as a small independent sanity source and may
        # carry the current programme even if the paginated guide omits it.
        events.extend(collect_events(now_showing))
        guide_events, pages = fetch_tv_guide(
            client,
            chosen,
            args.hours,
            max(1, args.page_size),
            max(1, args.max_pages),
        )
        events.extend(guide_events)

    id_index = read_id_index(Path(args.id_index) if args.id_index else None)
    lang_tag = "ar" if chosen.casefold() in {"arabic", "ar"} else "en"
    root, stats = build_xml(events, id_index, args.hours, lang_tag)
    ET.indent(root, space="  ")
    out_path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "requested_hours": args.hours,
        "selected_content_language": chosen or None,
        "pages": pages,
        "detected_events_before_window_filter": len(events),
        **stats,
        "requests": client.requests,
        "error": error,
        "cloudflare_or_access_block": any(
            bool(row.get("challenge_or_block")) for row in client.requests
        ),
        "policy": "public metadata only; no Cloudflare/auth/geo/DRM bypass",
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))

    if report["cloudflare_or_access_block"]:
        return 10
    if not chosen:
        return 11
    return 0 if stats["channels"] and stats["programmes"] else 12


if __name__ == "__main__":
    raise SystemExit(main())
