#!/usr/bin/env python3
from __future__ import annotations
import argparse, gzip, json, re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

DT_RE=re.compile(r"^(\d{12}|\d{14})")

def parse_dt(v):
    m=DT_RE.match((v or "").strip())
    if not m: return None
    s=m.group(1)
    fmt="%Y%m%d%H%M%S" if len(s)==14 else "%Y%m%d%H%M"
    try: return datetime.strptime(s,fmt).replace(tzinfo=timezone.utc)
    except Exception: return None

def read_root(path:Path):
    raw=path.read_bytes()
    if path.suffix==".gz" or raw[:2]==b"\x1f\x8b": raw=gzip.decompress(raw)
    return ET.fromstring(raw)

def audit(path:Path):
    root=read_root(path)
    channels=[(c.get("id") or "").strip() for c in root.findall("channel")]
    channel_dupes=sorted([k for k,v in Counter(channels).items() if k and v>1])
    counts=Counter()
    future=Counter()
    exact=Counter()
    invalid_time=0
    now=datetime.now(timezone.utc)
    for p in root.findall("programme"):
        cid=(p.get("channel") or "").strip()
        counts[cid]+=1
        st=parse_dt(p.get("start"))
        sp=parse_dt(p.get("stop"))
        title="|".join((t.text or "").strip() for t in p.findall("title"))
        exact[(cid,p.get("start") or "",p.get("stop") or "",title)] += 1
        if not st or not sp or sp<=st:
            invalid_time += 1
            continue
        if sp>now:
            future[cid]+=1
    ids=[c for c in channels if c]
    zero=sorted([c for c in ids if counts[c]==0])
    future_zero=sorted([c for c in ids if future[c]==0])
    prog_dupes=sum(v-1 for v in exact.values() if v>1)
    return {
        "file":str(path),
        "channels":len(ids),
        "programmes":sum(counts.values()),
        "channel_id_duplicates":channel_dupes,
        "duplicate_programmes":prog_dupes,
        "invalid_time_programmes":invalid_time,
        "zero_epg_channels":zero,
        "future_zero_epg_channels":future_zero,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("feeds",nargs="+")
    ap.add_argument("--json",required=True)
    ap.add_argument("--md",required=True)
    a=ap.parse_args()
    rows=[audit(Path(x)) for x in a.feeds if Path(x).exists()]
    out={"generated_utc":datetime.now(timezone.utc).isoformat(),"sources":rows}
    Path(a.json).parent.mkdir(parents=True,exist_ok=True)
    Path(a.json).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    md=["# EPG Source Monitoring","",f"Generated: {out['generated_utc']}","",
        "| Feed | Channels | Programmes | Dup IDs | Dup programmes | Invalid times | Zero EPG | Future-zero |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        md.append(f"| {Path(r['file']).name} | {r['channels']} | {r['programmes']} | {len(r['channel_id_duplicates'])} | {r['duplicate_programmes']} | {r['invalid_time_programmes']} | {len(r['zero_epg_channels'])} | {len(r['future_zero_epg_channels'])} |")
    Path(a.md).write_text("\n".join(md)+"\n",encoding="utf-8")
    hard=sum(len(r["channel_id_duplicates"])+r["invalid_time_programmes"] for r in rows)
    return 2 if hard else 0
if __name__=="__main__": raise SystemExit(main())
