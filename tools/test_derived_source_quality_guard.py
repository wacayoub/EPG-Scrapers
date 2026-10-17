# -*- coding: utf-8 -*-
"""Offline unit tests for per-ID MENA quality and fallback routing."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from derived_source_quality_guard import source_flags, classify, choose

NOW=datetime(2026,10,17,11,30,tzinfo=timezone.utc)

class SourceGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.feeds=root/"feeds"
        self.reports=root/"reports"
        self.feeds.mkdir()
        self.reports.mkdir()
        self.source="stctv"
        self.raw=b"\x1f\x8bA-SYNTHETIC-FIXTURE"
        self.pub={
            "sha256":hashlib.sha256(self.raw).hexdigest(),
            "size_bytes":len(self.raw),
            "generated_utc":NOW.isoformat(),
        }
        self.quality={
            "source":"stctv","source_file":"stctv.xml.gz",
            "generated_utc":NOW.isoformat(),
            "quality_status":"WARN",
            "suspected_placeholder_channels":[{"id":"AbuDhabiSports2.ae@SD","count":13}],
        }
        self.save()
    def save(self):
        (self.feeds/(self.source+".xml.gz")).write_bytes(self.raw)
        (self.feeds/(self.source+".json")).write_text(json.dumps(self.pub),encoding="utf-8")
        (self.reports/(self.source+"-quality.json")).write_text(json.dumps(self.quality),encoding="utf-8")
    def flags(self):
        return source_flags(self.source,self.feeds,self.reports,NOW)
    def test_identified_suspect_is_not_healthy(self):
        flags=self.flags()
        self.assertIn("AbuDhabiSports2.ae@SD",flags)
        self.assertEqual(classify(flags,"AbuDhabiSports2.ae@SD"),"SUSPECT_PLACEHOLDER")
        self.assertEqual(classify(flags,"OSNComedy.ae@SD"),"NO_PLACEHOLDER_FLAG")
    def test_modified_published_gzip_is_not_trusted(self):
        self.raw=b"different-but-valid-size---"
        self.save()
        self.assertIsNone(self.flags())
    def test_old_quality_report_is_not_trusted(self):
        self.quality["generated_utc"]=(NOW-timedelta(days=2)).isoformat()
        self.save()
        self.assertIsNone(self.flags())
    def test_stale_published_data_is_unknown(self):
        self.pub["generated_utc"]=(NOW-timedelta(days=9)).isoformat()
        self.quality["generated_utc"]=self.pub["generated_utc"]
        self.save()
        self.assertIsNone(self.flags())
    def test_missing_flags_are_unknown_not_clean(self):
        self.quality.pop("suspected_placeholder_channels")
        self.save()
        self.assertEqual(classify(self.flags(),"AbuDhabiSports2.ae@SD"),"UNKNOWN")
    def test_suspect_cannot_win_against_unflagged_detailed_guide(self):
        rows=[
            {"source":"stctv","score":100,"source_evidence":"SUSPECT_PLACEHOLDER",
             "qualified":False,"metrics":{"future_programmes":49}},
            {"source":"starzplay","score":31,"source_evidence":"NO_PLACEHOLDER_FLAG",
             "qualified":False,"metrics":{"future_programmes":36}},
            {"source":"sport24","score":0,"source_evidence":"NO_PLACEHOLDER_FLAG",
             "qualified":False,"metrics":{"future_programmes":0}},
        ]
        picked,why=choose(rows,{"sport24":0,"starzplay":1,"stctv":2})
        self.assertEqual(picked["source"],"starzplay")
        self.assertEqual(why,"degraded_unflagged_candidate")
    def test_verified_other_source_beats_higher_suspect_score(self):
        rows=[
            {"source":"stctv","score":100,"source_evidence":"SUSPECT_PLACEHOLDER",
             "qualified":False,"metrics":{"future_programmes":49}},
            {"source":"osn","score":81,"source_evidence":"NO_PLACEHOLDER_FLAG",
             "qualified":True,"metrics":{"future_programmes":30}},
        ]
        picked,why=choose(rows,{"stctv":0,"osn":1})
        self.assertEqual(picked["source"],"osn")
        self.assertEqual(why,"preferred_healthy_source")
    def test_only_suspect_is_not_pretended_healthy(self):
        rows=[{"source":"stctv","score":100,"source_evidence":"SUSPECT_PLACEHOLDER",
               "qualified":False,"metrics":{"future_programmes":49}}]
        picked,why=choose(rows,{"stctv":0})
        self.assertEqual(picked["source"],"stctv")
        self.assertEqual(why,"degraded_no_unflagged_guide")

if __name__ == "__main__":
    unittest.main()
