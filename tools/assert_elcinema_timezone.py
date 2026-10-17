#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail closed if ElCinema's deployed runtime misreads Morocco legal GMT.

Morocco decree 2.26.530 (25 June 2026), official gazette 7521:
20 September 2026 02:00 local: move from UTC+01 to UTC+00.
This checks the actual Python and Node Intl/ICU libraries used by the
ElCinema grabber. It does not infer the timezone of external providers or
shift XMLTV timestamps. UTC XMLTV remains canonical.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

CHECKS = (
    ("2026-09-19T20:00:00+00:00", 60),
    ("2026-10-17T20:00:00+00:00", 0),
    ("2026-11-15T20:00:00+00:00", 0),
    ("2027-04-15T20:00:00+00:00", 0),
)
CASABLANCA = ZoneInfo("Africa/Casablanca")


def check_python():
    results = []
    for instant, expected_minutes in CHECKS:
        utc = datetime.fromisoformat(instant)
        local = utc.astimezone(CASABLANCA)
        minutes = int(local.utcoffset().total_seconds() / 60)
        if minutes != expected_minutes:
            raise RuntimeError(
                "ELCINEMA_MOROCCO_STALE_TZDATA: Python date=%s offset=%s expected=%s"
                % (instant, minutes, expected_minutes)
            )
        results.append({"utc": instant, "casablanca_offset_minutes": minutes})
    return results


def check_node():
    script = r"""
const checks = JSON.parse(process.argv[1]);
for (const [date, expectedOffsetMinutes] of checks) {
  const instant = new Date(date);
  const f = new Intl.DateTimeFormat('en-GB', {
    timeZone:'Africa/Casablanca', year:'numeric',month:'2-digit',
    day:'2-digit',hour:'2-digit',minute:'2-digit',
    hourCycle:'h23'
  });
  const parts=Object.fromEntries(f.formatToParts(instant)
    .filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
  const projected=Date.UTC(
    Number(parts.year),Number(parts.month)-1,Number(parts.day),
    Number(parts.hour),Number(parts.minute));
  const offset=Math.round((projected-instant.getTime())/60000);
  if (offset!==expectedOffsetMinutes) {
    console.error('ELCINEMA_MOROCCO_STALE_TZDATA: Node Intl',date,offset,
      'expected',expectedOffsetMinutes);
    process.exit(2);
  }
  console.log('ELCINEMA_NODE_TZ_CHECK',date,offset);
}
"""
    try:
        run = subprocess.run(
            ["node", "-e", script, json.dumps(CHECKS)],
            capture_output=True, text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("ELCINEMA_NODE_TZ_UNAVAILABLE") from exc
    if run.returncode != 0:
        raise RuntimeError(run.stdout + run.stderr)
    return run.stdout.strip().splitlines()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", help="Optional already-patched ElCinema JS adapter")
    args = parser.parse_args()
    if args.adapter:
        from elcinema_midnight_patch import PIN_TZ
        data = Path(args.adapter).read_text(encoding="utf-8")
        if data.count(PIN_TZ) != 1:
            raise RuntimeError("ELCINEMA_ADAPTER_NOT_PINNED_TO_CASABLANCA")
    results = check_python()
    node_results = check_node()
    print("ELCINEMA_MOROCCO_LEGAL_TIMEZONE_PASS", json.dumps({
        "legal_timezone": "Africa/Casablanca",
        "after_2026_09_20": "UTC+00:00 permanent",
        "python_results": results,
        "node_results": node_results,
        "adapter_checked": bool(args.adapter),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
