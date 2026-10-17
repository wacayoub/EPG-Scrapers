#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch upstream ElCinema adapter's confirmed programme-midnight regression.

A broadcast grid may begin in the evening and continue after midnight. The
upstream adapter parses each HH:MM against the section heading date even when
programme order crosses midnight, which sends the next day's early programmes
to yesterday. This PATCH is conditional, narrow, pinned and fail-closed.

Does not touch receiver, provider copyrighted texts or published feeds.
"""
from __future__ import annotations
import argparse
from pathlib import Path

OLD = """    const items = parseItems(content, channel, date)
    items.forEach(item => {
      const start = parseStart(item, date)
      const duration = parseDuration(item)
"""
NEW = """    const items = parseItems(content, channel, date)
    // An ElCinema section can run 18:00 through the next day's daytime.
    // The source clock rolls from late evening back to early morning once
    // inside a section. Anchor those post-midnight slots to tomorrow,
    // without changing the source's local clock or fabricating programmes.
    let broadcastDayOffset = 0
    let previousLocalStart = null
    items.forEach(item => {
      let start = parseStart(item, date.add(broadcastDayOffset, 'day'))
      if (previousLocalStart && start.isBefore(previousLocalStart)) {
        const backwardsMinutes = previousLocalStart.diff(start, 'minute')
        if (previousLocalStart.hour() >= 17 && start.hour() <= 12 &&
            backwardsMinutes >= 420 && backwardsMinutes <= 1440) {
          broadcastDayOffset += 1
          start = parseStart(item, date.add(broadcastDayOffset, 'day'))
        }
      }
      previousLocalStart = start
      const duration = parseDuration(item)
"""
OLD_TZ = "return dayjs.tz(time, 'YYYY-MM-DD hh:mm A', dayjs.tz.guess())"
PIN_TZ = "return dayjs.tz(time, 'YYYY-MM-DD hh:mm A', 'Africa/Casablanca')"

def patch(src: str) -> str:
    if not isinstance(src, str) or len(src) > 100000:
        raise ValueError("unexpected upstream adapter")
    if src.count(NEW) == 1 and src.count(PIN_TZ) == 1:
        return src
    if src.count(OLD) != 1:
        raise ValueError("ElCinema parser changed: no exact unique day-rollover anchor")
    if src.count(OLD_TZ) != 1:
        raise ValueError("ElCinema timezone parser changed: no exact unique TZ anchor")
    return src.replace(OLD, NEW, 1).replace(OLD_TZ, PIN_TZ, 1)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    path = Path(args.config)
    raw = path.read_text(encoding="utf-8")
    new = patch(raw)
    if new != raw:
        path.write_text(new, encoding="utf-8")
    print("ELCINEMA_MIDNIGHT_ROLLOVER_PATCH_VERIFIED",
          "changed=",new != raw, "tz=Africa/Casablanca")
if __name__=="__main__":
    main()
