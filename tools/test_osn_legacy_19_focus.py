# -*- coding: utf-8 -*-
"""No-network OSN Legacy focus identity and guide freshness regression."""
import json
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
import xml.etree.ElementTree as ET
from osn_legacy_19_focus import ALFA, PINOY, RADIO, FOCUS, catalogue, inspect, group

NOW=datetime(2026,10,17,13,0,tzinfo=timezone.utc)
def dt(date):
    return date.strftime("%Y%m%d%H%M%S %z")
def base_catalogue():
    return {"platforms":{"legacy":{"ar":{"items":[{"site_id":sid,"name":"Provider "+sid}
                                      for sid in FOCUS.values()]}}}}
def base_meta():
    return {"zero_epg_ids":list(FOCUS)}
def fake_xml(cid,start,stop,title="Real show"):
    root=ET.Element("tv")
    p=ET.SubElement(root,"programme",channel=cid,start=dt(start),stop=dt(stop))
    ET.SubElement(p,"title").text=title
    return root

class TestLegacy(unittest.TestCase):
    def test_19_providers_are_disjoint_8_9_2(self):
        self.assertEqual(len(FOCUS),19)
        self.assertEqual((len(ALFA),len(PINOY),len(RADIO)),(8,9,2))
        self.assertTrue(all(group(cid) in ("alfa","pinoy","radio") for cid in FOCUS))
    def test_exact_ids_and_guids_are_stable(self):
        c=catalogue(base_catalogue(),base_meta())
        self.assertEqual(len(c.findall("channel")),19)
        self.assertEqual({x.get("xmltv_id") for x in c.findall("channel")},set(FOCUS))
        self.assertEqual({x.get("site_id") for x in c.findall("channel")},set(FOCUS.values()))
    def test_missing_provider_guid_refused(self):
        fake=base_catalogue()
        fake["platforms"]["legacy"]["ar"]["items"].pop()
        with self.assertRaises(ValueError):
            catalogue(fake,base_meta())
    def test_when_osn_recovers_ids_reconfirmation_required(self):
        current=base_meta()
        current["zero_epg_ids"].remove("AlfaSeries.ae@SD")
        with self.assertRaises(ValueError):
            catalogue(base_catalogue(),current)
    def test_valid_current_and_future_programmes_count(self):
        c="Cinema1.ae@SD"
        root=fake_xml(c,NOW-timedelta(minutes=2),NOW+timedelta(hours=1))
        out=inspect(root,NOW)
        self.assertEqual(out["groups"]["alfa"]["ids_with_future_programmes"],1)
        self.assertEqual(out["ids_with_future_programmes"],1)
        self.assertEqual(len(out["missing"]),18)
        self.assertFalse(out["public_feeds_modified"])
    def test_invalid_titles_dont_count(self):
        c="CineMo.ph"
        root=fake_xml(c,NOW+timedelta(hours=1),NOW+timedelta(hours=2),"")
        out=inspect(root,NOW)
        self.assertEqual(out["invalid_rows"],1)
        self.assertEqual(out["ids_with_future_programmes"],0)
    def test_unrequested_id_is_rejected(self):
        root=fake_xml("OSNComedy.ae@SD",NOW,NOW+timedelta(hours=1))
        with self.assertRaises(ValueError):
            inspect(root,NOW)
    def test_expired_programmes_dont_count(self):
        root=fake_xml("AlfaSeries.ae@SD",NOW-timedelta(days=2),NOW-timedelta(days=1))
        self.assertEqual(inspect(root,NOW)["ids_with_future_programmes"],0)

if __name__=="__main__":
    unittest.main()
