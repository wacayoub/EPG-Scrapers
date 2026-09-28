#!/usr/bin/env python3
from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

FEEDS = Path("feeds")
REPORTS = Path("reports")
POLICY_PATH = Path("config/canonical-channel-policy.json")
AR = re.compile(r"[\u0600-\u06FF]")
LATIN = re.compile(r"[A-Za-z]")
DT_RE = re.compile(r"^(\d{12}|\d{14})(?:\s*([+-]\d{4}|Z))?")

DEFAULT_POLICY = {
    "default_source_order": [
        "morocco","alkass","tunisiatv","aljazeera","dubaiplus","shahid",
        "rotana","sport24","osn","bein","elcinema","starzplay","stctv"
    ],
    "quality": {
        "min_future_programmes": 1,
        "min_future_hours": 4,
        "min_description_pct": 35,
        "min_language_fit_pct": 50,
    },
    "family_rules": [],
    "alias_groups": [],
}


def load_policy():
    if not POLICY_PATH.exists():
        return DEFAULT_POLICY
    data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    out = dict(DEFAULT_POLICY)
    out.update(data)
    out["quality"] = {**DEFAULT_POLICY["quality"], **data.get("quality", {})}
    return out


POLICY = load_policy()
PRIORITY = POLICY["default_source_order"]


def read_root(path: Path):
    raw = path.read_bytes()
    if path.suffix == ".gz" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return ET.fromstring(raw)


def clone(node):
    return ET.fromstring(ET.tostring(node, encoding="utf-8"))


def text_of(node, tag):
    for x in node.findall(tag):
        text = (x.text or "").strip()
        if text:
            return text
    return ""


def display_name(node, fallback):
    return text_of(node, "display-name") or fallback


def parse_dt(value):
    m = DT_RE.match((value or "").strip())
    if not m:
        return None
    digits, off = m.group(1), m.group(2)
    fmt = "%Y%m%d%H%M%S" if len(digits) == 14 else "%Y%m%d%H%M"
    dt = datetime.strptime(digits, fmt)
    if not off or off == "Z":
        return dt.replace(tzinfo=timezone.utc)
    sign = 1 if off[0] == "+" else -1
    mins = sign * (int(off[1:3]) * 60 + int(off[3:5]))
    return dt.replace(tzinfo=timezone(timedelta(minutes=mins))).astimezone(timezone.utc)


def source_data(name):
    path = FEEDS / f"{name}.xml.gz"
    if not path.exists():
        return {}, defaultdict(list)
    root = read_root(path)
    channels = {}
    programmes = defaultdict(list)
    for ch in root.findall("channel"):
        cid = (ch.get("id") or "").strip()
        if cid:
            channels[cid] = ch
    for p in root.findall("programme"):
        cid = (p.get("channel") or "").strip()
        if cid in channels:
            programmes[cid].append(p)
    return channels, programmes


def pct(values, predicate):
    values = [x for x in values if x]
    if not values:
        return 0.0
    return round(100.0 * sum(1 for x in values if predicate(x)) / len(values), 1)


def metrics(rows):
    now = datetime.now(timezone.utc)
    future = []
    for p in rows:
        stop = parse_dt(p.get("stop") or p.get("start"))
        if stop and stop > now:
            future.append(p)
    sample = future or list(rows)
    titles = [text_of(p, "title") for p in sample]
    descs = [text_of(p, "desc") for p in sample]
    last = None
    for p in future:
        stop = parse_dt(p.get("stop") or p.get("start"))
        if stop and (last is None or stop > last):
            last = stop
    return {
        "programmes": len(rows),
        "future_programmes": len(future),
        "future_hours": round(max(0.0, (last - now).total_seconds() / 3600.0), 1) if last else 0.0,
        "description_pct": round(100.0 * sum(1 for d in descs if d) / len(sample), 1) if sample else 0.0,
        "arabic_title_pct": pct(titles, lambda x: bool(AR.search(x))),
        "arabic_desc_pct": pct(descs, lambda x: bool(AR.search(x))),
        "latin_title_pct": pct(titles, lambda x: bool(LATIN.search(x))),
    }


def family_rule(cid, name):
    hay = f"{cid} {name}".casefold()
    for rule in POLICY.get("family_rules", []):
        if any(str(t).casefold() in hay for t in rule.get("tokens", [])):
            return rule
    return {}


def profile_for(cid, name, explicit=None):
    if explicit:
        return explicit
    low = f"{cid} {name}".casefold()
    if "nationalgeographicabudhabi" in low or "national geographic abu dhabi" in low:
        return "arabic"
    return family_rule(cid, name).get("profile", "arabic")


def language_fit(profile, m):
    if profile == "hybrid":
        title_fit = max(m["latin_title_pct"], 100.0 - m["arabic_title_pct"])
        desc_fit = m["arabic_desc_pct"]
    else:
        title_fit = m["arabic_title_pct"]
        desc_fit = m["arabic_desc_pct"]
    return round((title_fit + desc_fit) / 2.0, 1)


def quality_score(profile, m):
    fit = language_fit(profile, m)
    return round(
        fit * 0.45
        + m["description_pct"] * 0.25
        + min(m["future_hours"], 48.0) / 48.0 * 20.0
        + min(m["future_programmes"], 40) / 40.0 * 10.0,
        2,
    )


def qualified(profile, m):
    q = POLICY["quality"]
    return (
        m["future_programmes"] >= q["min_future_programmes"]
        and m["future_hours"] >= q["min_future_hours"]
        and m["description_pct"] >= q["min_description_pct"]
        and language_fit(profile, m) >= q["min_language_fit_pct"]
    )


def preferred_sources(cid, name, explicit=None):
    if explicit:
        return list(explicit)
    rule = family_rule(cid, name)
    preferred = list(rule.get("preferred_sources", []))
    for src in PRIORITY:
        if src not in preferred:
            preferred.append(src)
    return preferred


def latest_stop(rows):
    stops = [(p.get("stop") or "").strip() for p in rows if (p.get("stop") or "").strip()]
    return max(stops) if stops else ""


def program_copy(p, cid):
    out = clone(p)
    out.set("channel", cid)
    return out


def channel_copy(ch, cid):
    out = clone(ch)
    out.set("id", cid)
    return out


def write_feed(name, channels, programmes, meta):
    root = ET.Element("tv", {
        "generator-info-name": meta.get("generator", "EPG-Scrapers derived feed"),
        "generator-info-url": "https://github.com/wacayoub/EPG-Scrapers",
    })
    for cid in sorted(channels, key=str.casefold):
        root.append(clone(channels[cid]))
    count = 0
    for cid in sorted(programmes, key=str.casefold):
        seen = set()
        for p in sorted(programmes[cid], key=lambda e: ((e.get("start") or ""), (e.get("stop") or ""))):
            title = "|".join((t.text or "").strip() for t in p.findall("title"))
            key = (p.get("start") or "", p.get("stop") or "", title)
            if key in seen:
                continue
            seen.add(key)
            root.append(clone(p))
            count += 1
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    gz = gzip.compress(xml, compresslevel=9, mtime=0)
    (FEEDS / f"{name}.xml.gz").write_bytes(gz)
    lines = []
    for cid in sorted(channels, key=str.casefold):
        lines.append(f"{cid}|{display_name(channels[cid], cid)}")
    (FEEDS / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    out = {
        "label": name,
        "channels": len(channels),
        "programmes": count,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(gz).hexdigest(),
        **meta,
    }
    (FEEDS / f"{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(name, len(channels), count)


# Explicit alias groups are the only place where different XMLTV IDs are
# considered the same real channel. This prevents accidental merging of
# regional variants that merely share a similar display name.
member_to_canonical = {}
alias_meta = {}
for group in POLICY.get("alias_groups", []):
    canonical = group["canonical_id"]
    alias_meta[canonical] = group
    for member in group.get("members", []):
        member_to_canonical[(member["source"], member["id"])] = canonical

sources = {name: source_data(name) for name in PRIORITY if (FEEDS / f"{name}.xml.gz").exists()}
groups = defaultdict(list)
for src in PRIORITY:
    if src not in sources:
        continue
    channels, programmes = sources[src]
    for cid, node in channels.items():
        canonical = member_to_canonical.get((src, cid), cid)
        rows = list(programmes.get(cid, []))
        groups[canonical].append({
            "source": src,
            "id": cid,
            "name": display_name(node, cid),
            "node": node,
            "rows": rows,
        })

merged_channels = {}
merged_programmes = defaultdict(list)
owners = {}
extensions = defaultdict(list)
routing = {}

for canonical, candidates in sorted(groups.items(), key=lambda x: x[0].casefold()):
    meta = alias_meta.get(canonical, {})
    sample = candidates[0]
    explicit_profile = meta.get("profile")
    profile = profile_for(canonical, sample["name"], explicit_profile)
    prefs = preferred_sources(canonical, sample["name"], meta.get("preferred_sources"))

    for c in candidates:
        c["metrics"] = metrics(c["rows"])
        c["profile"] = profile
        c["language_fit_pct"] = language_fit(profile, c["metrics"])
        c["score"] = quality_score(profile, c["metrics"])
        c["qualified"] = qualified(profile, c["metrics"])

    pref_index = {s: i for i, s in enumerate(prefs)}
    good = [c for c in candidates if c["qualified"]]
    if good:
        selected = sorted(good, key=lambda c: (pref_index.get(c["source"], 999), -c["score"]))[0]
        selection_reason = "preferred_healthy_source"
    else:
        selected = sorted(candidates, key=lambda c: (-c["score"], pref_index.get(c["source"], 999)))[0]
        selection_reason = "degraded_best_available"

    ordered = sorted(candidates, key=lambda c: (pref_index.get(c["source"], 999), -c["score"]))
    roles = {}
    role_no = 1
    for c in ordered:
        if c["source"] == prefs[0]:
            roles[(c["source"], c["id"])] = "MAIN"
        else:
            roles[(c["source"], c["id"])] = f"B{role_no}"
            role_no += 1

    merged_channels[canonical] = channel_copy(selected["node"], canonical)
    merged_programmes[canonical] = [program_copy(p, canonical) for p in selected["rows"]]
    owners[canonical] = selected["source"]

    cutoff = latest_stop(merged_programmes[canonical])
    used_extensions = []
    for c in ordered:
        if c is selected or not c["qualified"] or not cutoff:
            continue
        tail = [p for p in c["rows"] if (p.get("start") or "").strip() >= cutoff]
        if not tail:
            continue
        merged_programmes[canonical].extend(program_copy(p, canonical) for p in tail)
        used_extensions.append(c["source"])
        cutoff = latest_stop(merged_programmes[canonical])
    if used_extensions:
        extensions[canonical] = used_extensions

    routing[canonical] = {
        "profile": profile,
        "selected_source": selected["source"],
        "selected_id": selected["id"],
        "selected_role": roles.get((selected["source"], selected["id"]), "MAIN"),
        "selection_reason": selection_reason,
        "extensions": used_extensions,
        "candidates": [
            {
                "role": roles.get((c["source"], c["id"]), ""),
                "source": c["source"],
                "id": c["id"],
                "name": c["name"],
                "qualified": c["qualified"],
                "score": c["score"],
                "language_fit_pct": c["language_fit_pct"],
                **c["metrics"],
            }
            for c in ordered
        ],
    }

if merged_channels:
    write_feed("mena", merged_channels, merged_programmes, {
        "generator": "EPG-Scrapers canonical MENA merged feed",
        "priority": PRIORITY,
        "owners": owners,
        "extensions": dict(extensions),
        "routing_policy": "canonical channel -> healthy MAIN -> B1/B2; language/title/description quality gates; backup may extend only after selected source horizon",
    })

REPORTS.mkdir(parents=True, exist_ok=True)
report = {
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "channels": len(routing),
    "duplicate_groups": sum(1 for x in routing.values() if len(x["candidates"]) > 1),
    "backup_selected": sum(1 for x in routing.values() if x["selected_role"] != "MAIN"),
    "routing": routing,
}
(REPORTS / "canonical-source-routing.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

md = [
    "# Canonical EPG Main / Backup Routing",
    "",
    f"Generated: {report['generated_utc']}",
    "",
    f"Logical channels: **{report['channels']}**",
    f"Duplicate groups: **{report['duplicate_groups']}**",
    f"Backups currently selected: **{report['backup_selected']}**",
    "",
    "| Channel ID | Selected | Role | Profile | Candidates |",
    "|---|---|---|---|---|",
]
for cid, row in routing.items():
    if len(row["candidates"]) < 2:
        continue
    cands = ", ".join(
        f"{c['role']} {c['source']} ({c['score']}, {'OK' if c['qualified'] else 'LOW'})"
        for c in row["candidates"]
    )
    md.append(
        f"| {cid} | **{row['selected_source']}** | {row['selected_role']} | "
        f"{row['profile']} | {cands} |"
    )
(REPORTS / "canonical-source-routing.md").write_text("\n".join(md) + "\n", encoding="utf-8")
