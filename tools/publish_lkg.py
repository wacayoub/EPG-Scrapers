#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publish healthy candidate feeds independently with last-known-good protection.

A broken or incomplete source must never block publication of the other sources.
The strict 48h report remains diagnostic; this publisher applies conservative
per-source freshness/regression gates and keeps the previous feed on failure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import gzip
import json
import re
import shutil
import xml.etree.ElementTree as ET

OUT = Path("output/final")
FEEDS = Path("feeds")
REPORTS = Path("reports")
FEEDS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

POLICY = {
    "morocco":   {"min_channels": 5,  "min_programmes": 50,  "min_future_ratio": 0.70, "min_horizon_hours": 8},
    "elcinema":  {"min_channels": 20, "min_programmes": 100, "min_future_ratio": 0.70, "min_horizon_hours": 8},
    "osn":       {"min_channels": 20, "min_programmes": 100, "min_future_ratio": 0.80, "min_horizon_hours": 8},
    "bein":      {"min_channels": 8,  "min_programmes": 50,  "min_future_ratio": 0.65, "min_horizon_hours": 8},
    # Sport24 is event-driven; valid event schedules can naturally expose less
    # than eight continuous hours while still being fresher than the current LKG.
    "sport24":   {"min_channels": 2,  "min_programmes": 10,  "min_future_ratio": 0.60, "min_horizon_hours": 4},
}
DT_RE = re.compile(r"^(\d{12}|\d{14})(?:\s*([+-]\d{4}|Z))?")


def parse_dt(value: str | None):
    m = DT_RE.match((value or "").strip())
    if not m:
        return None
    digits, off = m.group(1), m.group(2)
    fmt = "%Y%m%d%H%M%S" if len(digits) == 14 else "%Y%m%d%H%M"
    x = datetime.strptime(digits, fmt)
    if not off or off == "Z":
        return x.replace(tzinfo=timezone.utc)
    sign = 1 if off[0] == "+" else -1
    mins = sign * (int(off[1:3]) * 60 + int(off[3:5]))
    return x.replace(tzinfo=timezone(timedelta(minutes=mins))).astimezone(timezone.utc)


def load_root(path: Path):
    raw = path.read_bytes()
    if path.suffix == ".gz" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return ET.fromstring(raw)


def stats(path: Path):
    root = load_root(path)
    channels = {(c.get("id") or "").strip() for c in root.findall("channel")}
    channels.discard("")
    now = datetime.now(timezone.utc)
    future_by_channel = {cid: 0 for cid in channels}
    programmes = 0
    invalid = 0
    latest_stop = None

    for p in root.findall("programme"):
        cid = (p.get("channel") or "").strip()
        start = parse_dt(p.get("start"))
        stop = parse_dt(p.get("stop"))
        if cid not in channels or not start or not stop or stop <= start:
            invalid += 1
            continue
        programmes += 1
        if stop > now:
            future_by_channel[cid] = future_by_channel.get(cid, 0) + 1
            if latest_stop is None or stop > latest_stop:
                latest_stop = stop

    future_channels = sum(1 for n in future_by_channel.values() if n > 0)
    ratio = future_channels / len(channels) if channels else 0.0
    horizon = ((latest_stop - now).total_seconds() / 3600.0) if latest_stop else 0.0
    return {
        "channels": len(channels),
        "programmes": programmes,
        "future_channels": future_channels,
        "future_ratio": ratio,
        "future_horizon_hours": max(0.0, horizon),
        "invalid_rows": invalid,
    }


def evaluate(key: str, candidate: Path, previous: Path):
    p = POLICY[key]
    cur = stats(candidate)
    reasons = []

    if cur["channels"] < p["min_channels"]:
        reasons.append(f"channels<{p['min_channels']}")
    if cur["programmes"] < p["min_programmes"]:
        reasons.append(f"programmes<{p['min_programmes']}")
    if cur["future_ratio"] < p["min_future_ratio"]:
        reasons.append(f"future_ratio<{p['min_future_ratio']:.2f}")
    min_horizon = float(p.get("min_horizon_hours", 8))
    if cur["future_horizon_hours"] < min_horizon:
        reasons.append(f"future_horizon<{min_horizon:g}h")
    if cur["invalid_rows"] > 0:
        reasons.append(f"invalid_rows={cur['invalid_rows']}")

    old = None
    if previous.exists() and previous.stat().st_size:
        try:
            old = stats(previous)
            # Reject catastrophic regressions while allowing legitimate lineup changes.
            if old["channels"] and cur["channels"] < max(p["min_channels"], int(old["channels"] * 0.60)):
                reasons.append("channel_regression>40%")
            if old["programmes"] and cur["programmes"] < max(p["min_programmes"], int(old["programmes"] * 0.35)):
                reasons.append("programme_regression>65%")
        except Exception as exc:
            old = {"warning": f"previous unreadable: {exc}"}

    return cur, old, reasons


result = {
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "sources": {},
}

for key in POLICY:
    src = OUT / f"{key}.xml.gz"
    dst = FEEDS / f"{key}.xml.gz"
    row = {"candidate": str(src), "published": False}

    if not src.exists() or not src.stat().st_size:
        row["decision"] = "KEEP_LKG"
        row["reasons"] = ["candidate_missing"]
        result["sources"][key] = row
        print("KEEP LKG", key, "candidate missing")
        continue

    try:
        cur, old, reasons = evaluate(key, src, dst)
        row["candidate_stats"] = cur
        if old is not None:
            row["previous_stats"] = old
        if reasons:
            row["decision"] = "KEEP_LKG"
            row["reasons"] = reasons
            result["sources"][key] = row
            print("KEEP LKG", key, "; ".join(reasons))
            continue

        shutil.copy2(src, dst)
        for ext in ("json", "txt"):
            p = OUT / f"{key}.{ext}"
            if p.exists():
                shutil.copy2(p, FEEDS / p.name)
        row["decision"] = "PUBLISH"
        row["published"] = True
        row["reasons"] = []
        result["sources"][key] = row
        print(
            "PUBLISHED", key,
            f"channels={cur['channels']}",
            f"programmes={cur['programmes']}",
            f"future={cur['future_ratio']:.1%}",
            f"horizon={cur['future_horizon_hours']:.1f}h",
        )
    except Exception as exc:
        row["decision"] = "KEEP_LKG"
        row["reasons"] = [f"candidate_error:{exc}"]
        result["sources"][key] = row
        print("KEEP LKG", key, exc)

(REPORTS / "publish-lkg.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
