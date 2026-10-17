# -*- coding: utf-8 -*-
"""Offline regression for post-publication ElCinema 97-ID source comparison."""
from datetime import datetime,timedelta,timezone
import unittest
from elcinema_postpublish_delta import compare

T=datetime(2026,10,17,10,tzinfo=timezone.utc)
def sample(after=False):
    t=T+timedelta(hours=4 if after else 0)
    rows=[]
    for i in range(97):
        fail=(i<31 if after else i<32)
        rows.append({
            "id":"id"+str(i),
            "status":"FAIL" if fail else "WARN",
            "reason":"TOO_SHORT+INTERNAL_GAP" if fail else "INTERNAL_GAP",
            "latest_stop_utc":(T+timedelta(hours=35+(18 if after else 0))).isoformat(),
            "future_hours":35,
            "max_gap_minutes":360,
        })
    meta={"generated_utc":t.isoformat(),"channels":97,"active_channels":97,
          "programmes":3750 if not after else 3900,
          "currently_on_air_channels":97,
          "sha256":"a"*64 if not after else "b"*64}
    audit={"generated_utc":(t+timedelta(seconds=2)).isoformat(),
           "feeds":[{"feed":"elcinema.xml.gz","rows":rows,
                     "failed_channels":sum(z["status"]=="FAIL" for z in rows),
                     "warning_channels":sum(z["status"]=="WARN" for z in rows)}]}
    return meta,audit

class Delta(unittest.TestCase):
    def test_improvement_real_missing_guides(self):
        a,b=sample();c,d=sample(True)
        x=compare(a,b,c,d)
        self.assertEqual(x["result_status"],"IMPROVED")
        self.assertEqual(x["48h_failed_before"],32)
        self.assertEqual(x["48h_failed_after"],31)
        self.assertEqual(x["previous_failed_ids_recovered"],["id31"])
        self.assertFalse(x["safe_to_claim_all_48h_recovered"])
        self.assertEqual(len(x["source_stop_extended_ids"]),97)
    def test_new_failure_is_not_success(self):
        a,b=sample();c,d=sample(True)
        d["feeds"][0]["rows"][60]["status"]="FAIL"
        d["feeds"][0]["rows"][60]["reason"]="TOO_SHORT+INTERNAL_GAP"
        d["feeds"][0]["failed_channels"]+=1
        d["feeds"][0]["warning_channels"]-=1
        x=compare(a,b,c,d)
        self.assertEqual(x["result_status"],"MIXED_OR_REGRESSION")
        self.assertFalse(x["source_quality_improved"])
    def test_missing_id_never_silently_accepted(self):
        a,b=sample();c,d=sample(True)
        d["feeds"][0]["rows"][70]["id"]="unknown"
        with self.assertRaises(ValueError):
            compare(a,b,c,d)
    def test_duplicate_id_is_blocked(self):
        a,b=sample();c,d=sample(True)
        d["feeds"][0]["rows"][70]["id"]="id71"
        with self.assertRaises(ValueError):
            compare(a,b,c,d)
    def test_stale_or_reverse_date_rejected(self):
        a,b=sample();c,d=sample(True)
        c["generated_utc"]=(T-timedelta(minutes=1)).isoformat()
        with self.assertRaises(ValueError):
            compare(a,b,c,d)
    def test_cohort_mismatch_fails(self):
        a,b=sample();c,d=sample(True)
        d["generated_utc"]=(T+timedelta(hours=12)).isoformat()
        with self.assertRaises(ValueError):
            compare(a,b,c,d)
    def test_48h_reports_not_automatically_fully_cured(self):
        a,b=sample();c,d=sample(True)
        self.assertFalse(compare(a,b,c,d)["safe_to_claim_all_48h_recovered"])
    def test_no_false_claim_for_same_failed_count(self):
        a,b=sample();c,d=sample()
        c["generated_utc"]=(T+timedelta(hours=5)).isoformat()
        d["generated_utc"]=c["generated_utc"]
        x=compare(a,b,c,d)
        self.assertEqual(x["result_status"],"NO_VERIFIED_48H_FAILURE_RECOVERY")

if __name__=="__main__":
    unittest.main()
