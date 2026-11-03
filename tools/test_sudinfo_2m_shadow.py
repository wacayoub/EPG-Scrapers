# -*- coding: utf-8 -*-
"""Offline tests for non-publishing Sudinfo 2M source; no network calls."""
import unittest
from datetime import date
from sudinfo_2m_shadow import parse_shadow

def page(events, header="Programme TV 2M Maroc - Aujourd'hui"):
    body = ["<html><head><title>%s</title></head><body><main><h1>%s</h1>" % (header,header)]
    for clock,name,minutes in events:
        body.append('<article class="programme"><span>%s</span><h3>%s</h3><small>Magazine</small><p>%smin</p></article>' % (clock,name,minutes))
    body.append("</main></body></html>")
    return "\n".join(body)

class SudinfoShadowTests(unittest.TestCase):
    def test_extract_real_day_without_publication(self):
        rows=[("06:05","Anis wa Manal",45),
              ("06:50","Coran avec lauréats Tajwid Al Qor'an",10),
              ("07:00","Ch'hiwat bladi",25),
              ("07:25","Sabahiyat 2M",90),
              ("08:55","Les filles de Lalla Mennana",70),
              ("21:00","Info soir",25),
              ("21:25","Bulletin Météo",5)]
        result=parse_shadow(page(rows),date(2026,10,17))
        self.assertEqual(result["candidate_count"],7)
        self.assertFalse(result["publication_authorized"])
        self.assertFalse(result["xmltv_ready"])
        self.assertFalse(result["page_date_verified"])
        self.assertFalse(result["source_timezone_verified"])
        self.assertEqual(result["rows"][5]["wall_time"],"2026-10-17T21:00")
        self.assertEqual(result["rows"][5]["title"],"Info soir")

    def test_after_midnight_rolls_forward(self):
        result=parse_shadow(page([("22:25","Les filles de Lalla Mennana",75),
                                  ("23:40","Basma",50),
                                  ("00:30","Nidae",20),
                                  ("00:50","Bahr Addalam",50)]),date(2026,10,17))
        self.assertEqual(result["rows"][2]["wall_time"],"2026-10-18T00:30")
        self.assertEqual(result["rows"][3]["wall_time"],"2026-10-18T00:50")

    def test_out_of_order_not_accepted(self):
        with self.assertRaises(ValueError):
            parse_shadow(page([("21:00","Info soir",25),
                               ("10:00","Unrelated",60)]),date(2026,10,17))

    def test_wrong_channel_rejected(self):
        with self.assertRaises(ValueError):
            parse_shadow(page([("10:00","Movie",60)],"Programme TV TF1"),date(2026,10,17))

    def test_duplicate_row_not_counted_twice(self):
        result=parse_shadow(page([("13:45","Al akhbar",40),("13:45","Al akhbar",40)]),date(2026,10,17))
        self.assertEqual(result["candidate_count"],1)

    def test_bad_duration_not_emitted(self):
        result=parse_shadow(page([("10:00","A Film",999)]),date(2026,10,17))
        self.assertEqual(result["candidate_count"],0)

    def test_weekday_permalink_does_not_accept_stale_date(self):
        with self.assertRaises(ValueError):
            parse_shadow(page([("09:00","Al akhbar",30)],"Programme TV 2M Maroc de samedi 12 septembre"),
                         date(2026,10,17),"samedi")

    def test_weekday_permalink_validates_printed_date(self):
        result=parse_shadow(page([("09:00","Al akhbar",30)],"Programme TV 2M Maroc de samedi 17 octobre"),
                            date(2026,10,17),"samedi")
        self.assertTrue(result["page_date_verified"])

    def test_generic_programme_not_trusted(self):
        result=parse_shadow(page([("06:05","Film",45),("06:50","Rachid Show",10)]),date(2026,10,17))
        self.assertEqual(result["non_generic_count"],1)

    def test_navigation_h3_excluded(self):
        h=page([("13:00","Mabrouk 3Lina",35)]).replace("</main>",'<nav><p>14:00</p><h3>Menu</h3><p>45min</p></nav></main>')
        result=parse_shadow(h,date(2026,10,17))
        self.assertEqual(result["candidate_count"],1)


if __name__ == "__main__":
    unittest.main()
