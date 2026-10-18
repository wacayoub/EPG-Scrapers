# -*- coding: utf-8 -*-
"""YAML and behavior checks: timezone-aware, targeted, and fail-closed EPG."""
from pathlib import Path
import unittest
import yaml

from tools import epg_schedule_policy

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows"


def load(name):
    # BaseLoader preserves the literal GitHub Actions 'on:' key (PyYAML SafeLoader
    # otherwise uses the YAML 1.1 boolean representation of on).
    data = yaml.load((WF / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(data, dict) and "on" in data
    return data


class TestScheduledWorkflows(unittest.TestCase):
    def test_main_sequence_once_each_casablanca_morning(self):
        p = load("daily-epg-chain.yml")
        self.assertEqual(p["on"]["schedule"], [{
            "cron": "15 7 * * *", "timezone": "Etc/GMT",
        }])
        self.assertEqual(len([key for key in p["jobs"] if key != "finalize"]), 7)
        self.assertNotIn("osn", p["jobs"])
        self.assertNotIn("shahid", p["jobs"])
        self.assertNotIn("sport24", p["jobs"])
        self.assertEqual(p["jobs"]["rotana"]["needs"], "alkass")
        self.assertNotIn("dubaiplus", p["jobs"])
        self.assertNotIn("aljazeera", p["jobs"])
        self.assertNotIn("starzplay", p["jobs"])
        self.assertIsNone(p["jobs"]["tunisiatv"].get("needs"))
        self.assertIn("epg-daily-chain", p["concurrency"]["group"])

    def test_1415_watchdog_is_not_full_chain_retry(self):
        p = load("epg-watchdog.yml")
        self.assertEqual(p["on"]["schedule"], [{
            "cron": "15 14 * * *", "timezone": "Etc/GMT",
        }])
        contents = (WF / "epg-watchdog.yml").read_text()
        self.assertNotIn("gh workflow run daily-epg-chain.yml", contents)
        self.assertIn("MENA", contents)

    def test_shahid_retry_is_manual_only_after_0339_schedule(self):
        p = load("epg-casablanca-targeted-retry.yml")
        self.assertNotIn("schedule", p["on"])
        self.assertIn("workflow_dispatch", p["on"])
        shahid = load("refresh-shahid.yml")
        self.assertEqual(shahid["on"]["schedule"], [{
            "cron": "39 3 * * *", "timezone": "Etc/GMT",
        }])
        self.assertIn("workflow_dispatch", shahid["on"])
        self.assertNotIn("push", shahid["on"])
        self.assertEqual(p["jobs"]["retry"]["with"]["source"], "${{ matrix.source }}")
        self.assertEqual(p["jobs"]["retry"]["strategy"]["max-parallel"], "1")
        self.assertEqual(p["jobs"]["retry"]["strategy"]["matrix"]["source"],
                         "${{ fromJSON(needs.decide.outputs.retry_sources) }}")
        self.assertEqual(tuple(epg_schedule_policy.TARGETS),
                         ("shahid",))
        self.assertIn("--active-chain", (WF / "epg-casablanca-targeted-retry.yml").read_text())
        self.assertIn("if ! gh run list", (WF / "epg-casablanca-targeted-retry.yml").read_text())

    def test_dubaiplus_exact_0444_gmt_only_one_source_schedule(self):
        p = load("refresh-dubaiplus.yml")
        self.assertEqual(p["on"]["schedule"], [{
            "cron": "44 4 * * *", "timezone": "Etc/GMT",
        }])
        self.assertIn("workflow_dispatch", p["on"])
        self.assertNotIn("push", p["on"])
        self.assertEqual(p["jobs"]["refresh"]["with"], {
            "source": "dubaiplus", "scheduled": "false",
        })
        chain = load("daily-epg-chain.yml")
        self.assertNotIn("dubaiplus", chain["jobs"])
        self.assertNotIn("aljazeera", chain["jobs"])
        self.assertNotIn("starzplay", chain["jobs"])
        self.assertIsNone(chain["jobs"]["tunisiatv"].get("needs"))

    def test_all_known_scheduled_workflows_are_fixed_gmt_zero(self):
        names = ("refresh-elcinema.yml", "refresh-osn.yml",
                 "refresh-bein.yml", "refresh-sport24.yml",
                 "refresh-shahid.yml", "refresh-dubaiplus.yml",
                 "refresh-aljazeera.yml", "refresh-starzplay.yml",
                 "daily-epg-chain.yml", "epg-watchdog.yml",
                 "epg-evening-casablanca.yml")
        for name in names:
            with self.subTest(workflow=name):
                p=load(name)
                self.assertTrue(p["on"]["schedule"])
                for entry in p["on"]["schedule"]:
                    self.assertEqual(entry["timezone"], "Etc/GMT")

    def test_evening_sports_and_morocco_are_independent(self):
        p = load("epg-evening-casablanca.yml")
        self.assertEqual(p["on"]["schedule"], [
            {"cron": "30 19 * * *", "timezone": "Etc/GMT"},
            {"cron": "30 20 * * *", "timezone": "Etc/GMT"},
        ])
        self.assertEqual(p["jobs"]["sports"]["strategy"]["matrix"]["source"],
                         ["alkass"])
        self.assertEqual(p["jobs"]["sports"]["strategy"]["max-parallel"], "1")
        self.assertEqual(p["jobs"]["morocco"]["with"]["source"], "morocco")
        self.assertIn("hour=$local_hour", (WF / "epg-evening-casablanca.yml").read_text())

    def test_no_receiver_install_or_unbounded_recursion(self):
        names = ("daily-epg-chain.yml", "epg-watchdog.yml",
                 "epg-casablanca-targeted-retry.yml", "epg-evening-casablanca.yml")
        for name in names:
            src = (WF / name).read_text(encoding="utf-8")
            for command in ("opkg install", "ssh ", "reboot", "/etc/enigma2", "wget -q"):
                with self.subTest(filename=name, command=command):
                    self.assertNotIn(command, src)
        self.assertNotIn("gh workflow run daily-epg-chain", (WF / "epg-watchdog.yml").read_text())


if __name__ == "__main__":
    unittest.main()
