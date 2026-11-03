# -*- coding: utf-8 -*-
"""Fixture-only tests for 2M Maroc data extraction; NO network or publication."""
from datetime import date
import unittest
from communesmaroc_2m_shadow import parse_html,quality_summary

DAY=date(2026,10,17)
def html(entries, button="Samedi 17 octobre", channel="Grille de 2M"):
    cards="\n".join('<div class="program-item d-flex align-items-center p-3">'
                    '<div class="hour">%s</div><div class="info-box flex-grow-1">'
                    '<h6>%s</h6><div>Émission</div></div></div>' %(clock,title)
                    for clock,title in entries)
    return ("<html><body><h1>%s</h1><button>%s</button>"
            "<nav><a>18 octobre</a><a>19 octobre</a></nav>"
            '<div class="accordion-body">%s</div></body></html>'%
            (channel,button,cards))

class TestShadowSource(unittest.TestCase):
    def test_main_day_recognized(self):
        a=parse_html(html([("06:05","Anis wa Manal"),("21:00","Info soir"),
                          ("21:25","Bulletin Météo")]),DAY)
        self.assertEqual(a["quality"]["candidate_count"],3)
        self.assertEqual(a["rows"][1]["wall_time"],"2026-10-17T21:00")
        self.assertFalse(a["quality"]["publication_authorized"])
        self.assertFalse(a["quality"]["timezone_verified"])

    def test_rollover_to_next_broadcast_day(self):
        a=parse_html(html([("22:20","Soirée Fonoun Marrakchiya"),
                            ("00:35","Bahr Addalam"),("01:25","Al Akhawat attalat")]),DAY)
        self.assertEqual(a["rows"][1]["wall_time"],"2026-10-18T00:35")
        self.assertEqual(a["rows"][2]["wall_time"],"2026-10-18T01:25")

    def test_other_selected_date_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_html(html([("21:00","Info soir")],button="Dimanche 18 octobre"),DAY)

    def test_other_channel_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_html(html([("21:00","Info soir")],channel="Grille de Al Aoula"),DAY)

    def test_duplicate_same_time_is_not_two_programmes(self):
        a=parse_html(html([("06:05","Anis wa Manal"),("06:05","Other programme"),
                          ("06:50","Coran avec lauréats")]),DAY)
        self.assertEqual(a["quality"]["duplicate_slots"],1)
        self.assertEqual(a["quality"]["candidate_count"],2)

    def test_near_duplicate_same_title_counted(self):
        a=parse_html(html([("06:50","Coran avec lauréats"),
                          ("06:55","Coran avec lauréats"),
                          ("07:00","Chhiwat bladi")]),DAY)
        self.assertEqual(a["quality"]["near_duplicate_titles"],1)
        self.assertEqual(a["quality"]["candidate_count"],2)

    def test_generic_titles_are_rejected(self):
        a=parse_html(html([("06:05","Film"),("07:00","Rachid Show")]),DAY)
        self.assertEqual(a["quality"]["generic_titles"],1)
        self.assertEqual(a["quality"]["candidate_count"],1)

    def test_cards_missing_time_rejected(self):
        raw=html([("XX:YY","Info soir"),("21:25","Bulletin Météo")])
        a=parse_html(raw,DAY)
        self.assertEqual(a["quality"]["invalid_cards"],1)
        self.assertEqual(a["quality"]["candidate_count"],1)

    def test_out_of_order_rejected(self):
        a=parse_html(html([("21:00","Info soir"),("10:00","Sabahiyat 2M")]),DAY)
        self.assertEqual(a["quality"]["out_of_order"],1)
        self.assertEqual(a["quality"]["candidate_count"],1)

    def test_no_cards_fails(self):
        with self.assertRaises(ValueError):
            parse_html("<html><h1>Grille de 2M</h1><button>Samedi 17 octobre</button></html>",DAY)

    def test_date_link_does_not_override_selected_day(self):
        with self.assertRaises(ValueError):
            parse_html(html([("21:00","Info soir")],button="Vendredi 16 octobre")
                       .replace("</nav>","<a>Samedi 17 octobre</a></nav>"),DAY)

    def test_report_does_not_output_titles(self):
        result=parse_html(html([("21:00","Info soir")]),DAY)
        summary=str(quality_summary(result))
        self.assertNotIn("Info soir",summary)
        self.assertNotIn("communesmaroc-2m",summary)

if __name__ == "__main__":
    unittest.main()
