#!/usr/bin/env python3
from pathlib import Path
import gzip, shutil, xml.etree.ElementTree as ET

OUT=Path("output/final")
FEEDS=Path("feeds")
FEEDS.mkdir(parents=True,exist_ok=True)

for key in ("morocco","elcinema","osn","bein","sport24"):
    src=OUT/f"{key}.xml.gz"
    if not src.exists() or not src.stat().st_size:
        print("KEEP LKG",key,"candidate missing")
        continue
    try:
        raw=gzip.decompress(src.read_bytes())
        root=ET.fromstring(raw)
        ch=len(root.findall("channel"))
        pr=len(root.findall("programme"))
        if ch < 1 or pr < 1:
            raise ValueError(f"empty feed channels={ch} programmes={pr}")
    except Exception as exc:
        print("KEEP LKG",key,exc)
        continue
    shutil.copy2(src,FEEDS/src.name)
    for ext in ("json","txt"):
        p=OUT/f"{key}.{ext}"
        if p.exists():
            shutil.copy2(p,FEEDS/p.name)
    print("PUBLISHED",key,ch,pr)
