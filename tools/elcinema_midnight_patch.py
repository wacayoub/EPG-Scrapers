#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch upstream ElCinema adapter's confirmed programme-midnight regression.

A broadcast grid may begin in the evening and continue after midnight. The
upstream adapter parses each HH:MM against the section heading date even when
programme order crosses midnight, which, depending on section anchoring, can send evening broadcasts
to the following day. The local date heading denotes when the section ENDS. This PATCH is conditional, narrow, pinned and fail-closed.

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
    // ElCinema's evening-to-morning section is labelled by the DAY IT ENDS.
    // Example: heading Sunday 18 lists Saturday evening then Sunday morning.
    // The earlier patch incorrectly moved Sunday morning to Monday, causing
    // 24-hour gaps in 95/97 channels. Keep morning on the heading date and
    // assign only the evening BEFORE the clock rollover to yesterday.
    const localStarts = items.map(item => parseStart(item, date))
    let rolloverIndex = -1
    for (let i = 1; i < localStarts.length; i++) {
      const previous = localStarts[i - 1]
      const next = localStarts[i]
      if (previous.isValid() && next.isValid() &&
          previous.hour() >= 17 && next.hour() <= 12 &&
          previous.diff(next, 'minute') >= 420 &&
          previous.diff(next, 'minute') <= 1440) {
        rolloverIndex = i
        break
      }
    }
    items.forEach((item, index) => {
      // A section without a clear 23:xx -> 00:xx boundary is ambiguous.
      // Leave its dates unchanged; never infer a day shift from the title.
      const broadcastDate = rolloverIndex >= 0 && index < rolloverIndex
        ? date.subtract(1, 'day') : date
      const start = parseStart(item, broadcastDate)
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
