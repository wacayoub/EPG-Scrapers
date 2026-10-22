# -*- coding: utf-8 -*-
"""No-network tests of ElCinema cohort comparison, no EPG sources rewritten."""
import unittest
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from elcinema_publication_delta_readonly import analyze

T=datetime(2026,10,17,12,4,tzinfo=timezone.utc)
def cohort(t,fail=True,active=2):
    meta={"label":"elcinema","generated_utc":t.isoformat(),"channels":2,
          "active_channels":active,"programmes":70,"sha256":"0"*64,"size_bytes":100}
    rows=[{"id":"A","status":"FAIL" if fail else "WARN",
           "reason":"TOO_SHORT+INTERNAL_GAP" if fail else "INTERNAL_GAP",
           "latest_stop_utc":(t+timedelta(hours=35)).isoformat(),
           "max_gap_minutes":360},
          {"id":"B","status":"PASS","reason":"",
           "latest_stop_utc":(t+timedelta(hours=48)).isoformat(),
           "max_gap_minutes":0}]
    audit={"generated_utc":t.isoformat(),
           "feeds":[{"feed":"elcinema.xml.gz","channels":2,
                     "failed_channels":int(fail),"warning_channels":int(not fail),
                     "invalid_times":0,"orphan_programmes":0,"rows":rows}]}
    return meta,audit

class TestDelta(unittest.TestCase):
    def test_same_snapshot_does_not_pretend_repaired(self):
        a,b=cohort(T)
        x=analyze(a,b,a,b)
        self.assertEqual(x["decision"],"NO_NEW_PUBLICATION")
        self.assertFalse(x["release_quality_certified"])
    def test_fixed_fail_and_no_old_event_lost(self):
        a,b=cohort(T)
        c,d=cohort(T+timedelta(hours=1),fail=False)
        c["sha256"]="1"*64
        x=analyze(a,b,c,d)
        self.assertEqual(x["failed_ids_before"],1)
        self.assertEqual(x["failed_ids_after"],0)
        self.assertEqual(x["decision"],"NO_CRITICAL_REGRESSION_DETECTED")
    def test_new_fail_blocks_green_claim(self):
        a,b=cohort(T,fail=False)
        c,d=cohort(T+timedelta(hours=1),fail=True)
        x=analyze(a,b,c,d)
        self.assertEqual(x["decision"],"REGRESSION_REVIEW")
        self.assertEqual(x["regressed_to_fail_count"],1)
    def test_regressed_last_programme_stop(self):
        a,b=cohort(T)
        c,d=cohort(T+timedelta(hours=1))
        d["feeds"][0]["rows"][1]["latest_stop_utc"]=(T-timedelta(hours=3)).isoformat()
        x=analyze(a,b,c,d)
        self.assertEqual(x["decision"],"REGRESSION_REVIEW")
        self.assertEqual(x["shorter_last_stop_count"],1)
    def test_channel_loss_fails_closed(self):
        a,b=cohort(T)
        c,d=cohort(T+timedelta(hours=1))
        d["feeds"][0]["rows"].pop()
        with self.assertRaises(ValueError):
            analyze(a,b,c,d)
    def test_stale_mismatched_qa_cohort_fails_closed(self):
        a,b=cohort(T)
        c,d=cohort(T+timedelta(hours=1))
        d["generated_utc"]=(T-timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):
            analyze(a,b,c,d)
    def test_duplicate_channel_ids_fail_closed(self):
        a,b=cohort(T)
        c,d=cohort(T+timedelta(hours=1))
        d["feeds"][0]["rows"][1]["id"]="A"
        with self.assertRaises(ValueError):
            analyze(a,b,c,d)
    def test_no_synthetic_epg_writes(self):
        a,b=cohort(T)
        c,d=cohort(T+timedelta(hours=1))
        old=deepcopy((a,b,c,d))
        x=analyze(a,b,c,d)
        self.assertEqual((a,b,c,d),old)
        self.assertFalse(x["xmltv_published_by_this_check"])
        self.assertFalse(x["receiver_modified"])

if __name__=="__main__":
    unittest.main()
