#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only per-ID source quality gate for canonical MENA routing.

The candidate's language / hours score is not proof that its programme titles
are genuine. A freshly published, hash-verified quality report is used to
exclude known placeholder-looking IDs from healthy auto selection. Missing
evidence is UNKNOWN, never silently certified CLEAN.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

MAX_SIZE = 12 * 1024 * 1024
MAX_AGE = 72 * 3600
MAX_COHORT_SKEW = 15 * 60


def _time(s):
    if not isinstance(s, str):
        raise ValueError("invalid timestamp")
    dt = datetime.fromisoformat(s.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(timezone.utc)


def source_flags(source, feeds, reports, now=None):
    """Return suspect-id set, or None if provenance of the report is unverified."""
    if not source or not source.replace("_","").isalnum():
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        feed_path = Path(feeds) / (source + ".xml.gz")
        meta = json.loads((Path(feeds) / (source + ".json")).read_text(encoding="utf-8"))
        quality = json.loads((Path(reports) / (source + "-quality.json")).read_text(encoding="utf-8"))
        pub = _time(meta["generated_utc"])
        measured = _time(quality["generated_utc"])
        if (now - pub).total_seconds() < -3600 or (now - pub).total_seconds() > MAX_AGE:
            return None
        if abs((pub - measured).total_seconds()) > MAX_COHORT_SKEW:
            return None
        if quality.get("source") != source or quality.get("source_file") != source + ".xml.gz":
            return None
        if quality.get("quality_status") not in ("PASS","WARN"):
            return None
        if not feed_path.is_file() or feed_path.is_symlink():
            return None
        raw = feed_path.read_bytes()
        if not 0 < len(raw) <= MAX_SIZE or len(raw) != meta.get("size_bytes"):
            return None
        if hashlib.sha256(raw).hexdigest() != meta.get("sha256"):
            return None
        entries = quality.get("suspected_placeholder_channels")
        if not isinstance(entries, list):
            return None
        out = set()
        for row in entries:
            ident = row.get("id") if isinstance(row, dict) else row
            if not isinstance(ident, str) or not ident.strip():
                return None
            out.add(ident.strip())
        return out
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        return None


def classify(flags, cid):
    if flags is None:
        return "UNKNOWN"
    return "SUSPECT_PLACEHOLDER" if cid in flags else "NO_PLACEHOLDER_FLAG"


def choose(candidates, pref_index):
    """Select without promoting a suspect candidate over an unflagged option.

    Explicitly does NOT certify publisher origin or native receiver EPG.
    The final degraded fallback retains its warning in the routing report.
    """
    good = [c for c in candidates if c["qualified"]]
    if good:
        return (sorted(good,key=lambda c:(pref_index.get(c["source"],999), -c["score"]))[0],
                "preferred_healthy_source")
    alternatives = [
        c for c in candidates
        if c["source_evidence"] != "SUSPECT_PLACEHOLDER"
        and c["metrics"]["future_programmes"] > 0
    ]
    if alternatives:
        return (sorted(alternatives,key=lambda c:(-c["score"],pref_index.get(c["source"],999)))[0],
                "degraded_unflagged_candidate")
    return (sorted(candidates,key=lambda c:(-c["score"],pref_index.get(c["source"],999)))[0],
            "degraded_no_unflagged_guide")
