# -*- coding: utf-8 -*-
"""Fixture-only OSN donor tests: avoid importing unrelated channels or old EPG."""
import gzip,hashlib,json,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from osn_missing_donor_scan_readonly import published,candidates,analyze,ALIAS
NOW=datetime(2026,10,17,12,0,tzinfo=timezone.utc)
def dt(d):return d.strftime("%Y%m%d%H%M%S %z")
def xml(rows):
    root=ET.Element("tv")
    for cid,start,stop,title in rows:
        p=ET.SubElement(root,"programme",channel=cid,start=dt(start),stop=dt(stop))
        ET.SubElement(p,"title").text=title
    return ET.tostring(root,encoding="utf8")
class Safety(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.repo=Path(tmp.name);(self.repo/"feeds").mkdir()
        (self.repo/"feeds"/"osn.json").write_text(json.dumps({"zero_epg_ids":["osn.216","AlfaSeries.ae@SD"]}))
    def donor(self,source,rows,offset=0):
        raw=gzip.compress(xml(rows))
        (self.repo/"feeds"/f"{source}.xml.gz").write_bytes(raw)
        meta={"generated_utc":(NOW-timedelta(hours=offset)).isoformat(),
              "sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw)}
        (self.repo/"feeds"/f"{source}.json").write_text(json.dumps(meta))
    def test_good_verified_alias_is_found_but_not_imported(self):
        self.donor("shahid",[("CinemaOne.ph",NOW,NOW+timedelta(hours=1),"Authentic Show")])
        report=analyze(self.repo,NOW)
        self.assertEqual(report["targets_with_any_candidate"],1)
        self.assertEqual(report["donors_by_target"]["osn.216"][0]["source"],"shahid")
        self.assertFalse(report["automatic_source_acceptance"])
        self.assertFalse(report["feed_republished"])
    def test_same_time_wrong_id_never_considered(self):
        self.donor("shahid",[("OtherStation",NOW,NOW+timedelta(hours=1),"Authentic Show")])
        self.assertEqual(analyze(self.repo,NOW)["targets_with_any_candidate"],0)
    def test_past_event_and_no_title_not_detected(self):
        self.donor("shahid",[("CinemaOne.ph",NOW-timedelta(days=1),NOW-timedelta(hours=1),"Authentic Show"),
                             ("CinemaOne.ph",NOW,NOW+timedelta(hours=1),"")])
        self.assertEqual(analyze(self.repo,NOW)["targets_with_any_candidate"],0)
    def test_checksum_mismatch_blocks(self):
        self.donor("shahid",[("CinemaOne.ph",NOW,NOW+timedelta(hours=1),"Authentic Show")])
        d=self.repo/"feeds"/"shahid.xml.gz";d.write_bytes(d.read_bytes()+b"damaged")
        root,state=published("shahid",self.repo,NOW)
        self.assertIsNone(root)
        self.assertEqual(state,"sha_mismatch")
    def test_stale_feed_unavailable(self):
        self.donor("shahid",[("CinemaOne.ph",NOW,NOW+timedelta(hours=1),"Authentic Show")],offset=120)
        root,state=published("shahid",self.repo,NOW)
        self.assertEqual(state,"stale")
        self.assertIsNone(root)
    def test_absent_independent_sources_no_false_claim(self):
        self.assertEqual(analyze(self.repo,NOW)["targets_with_any_candidate"],0)
if __name__=="__main__":
    unittest.main()
