# -*- coding: utf-8 -*-
"""Zero-network proof that XMLTV quality and time errors fail closed."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from epgpw_2m_direct_api_shadow import inspect_xml, inspect_json

NOW=datetime(2026,10,17,12,0,tzinfo=timezone.utc)
def feed(start="20261017113000 +0000", stop="20261017123000 +0000",
         channel="2M Maroc",name="Info soir"):
    return (('<tv><channel id="445700"><display-name>'+channel+'</display-name></channel>'
             '<programme channel="445700" start="'+start+'" stop="'+stop+'">'
             '<title>'+name+'</title></programme></tv>').encode()
class TestDirect2M(unittest.TestCase):
    def test_valid_program_now_utc(self):
        r=inspect_xml(feed(),NOW)
        self.assertEqual(r["events_current"],1)
        self.assertEqual(r["events_future_48h"],1)
        self.assertTrue(r["channel_name_matches_2m_maroc"])
        self.assertFalse(r["redistribution_authorized"])
    def test_2m_world_name_not_assumed_identical(self):
        self.assertFalse(inspect_xml(feed(channel="2M Monde"),NOW)["channel_name_matches_2m_maroc"])
    def test_no_current_program_not_ready(self):
        r=inspect_xml(feed(start="20261016013000 +0000",stop="20261016023000 +0000"),NOW)
        self.assertFalse(r["cache_now_and_future_verified"])
    def test_missing_title_does_not_count_current(self):
        r=inspect_xml(feed(name=""),NOW)
        self.assertEqual(r["events_current"],0)
        self.assertEqual(r["untitled"],1)
    def test_missing_timezone_does_not_count_as_valid(self):
        r=inspect_xml(feed(start="20261017113000",stop="20261017123000"),NOW)
        self.assertEqual(r["bad_times"],1)
        self.assertEqual(r["events_current"],0)
    def test_invalid_duration_does_not_count(self):
        r=inspect_xml(feed(stop="20261017113000 +0000"),NOW)
        self.assertEqual(r["bad_times"],1)
    def test_json_has_exact_channel_identity_and_utc(self):
        raw=json.dumps({"name":"2M Maroc","end_date":"2026-10-18",
          "epg_list":[{"title":"Info soir","start_date":"2026-10-17T19:00:00+00:00"},
                      {"title":"Rachid Show","start_date":"2026-10-18T16:00:00+00:00"}]}).encode()
        r=inspect_json(raw,NOW)
        self.assertEqual(r["future_starts_in_48h"],2)
        self.assertEqual(r["info_soir_start_utc_samples"],["2026-10-17T19:00Z"])
        self.assertFalse(r["redistribution_authorized"])
    def test_json_stale_rejected_by_window(self):
        raw=json.dumps({"name":"2M Maroc","epg_list":[{"title":"Info soir",
              "start_date":"2026-10-03T19:00:00+00:00"}]}).encode()
        self.assertEqual(inspect_json(raw,NOW)["future_starts_in_48h"],0)
    def test_not_xmltv_rejected(self):
        with self.assertRaises(ValueError):
            inspect_xml(b"<html></html>",NOW)
    def test_no_full_program_titles_printed(self):
        r=inspect_xml(feed(name="Secret unreleased long programme title"),NOW)
        self.assertNotIn("Secret unreleased",json.dumps(r))
if __name__=="__main__":
    unittest.main()
