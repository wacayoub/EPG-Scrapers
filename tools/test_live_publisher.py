#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline synthetic proof that partial real EPG beats expired LKG.

Never fetch providers, update GitHub, edit receiver or fabricate source data.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "tools/publish_lkg.py"
PACKER = ROOT / "tools/source_feed_pack.py"


def timeline(channels=9, live=5, horizon=12, shift=-5,
             period=30, invalid_titles=0):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    tv = ET.Element("tv")
    for idx in range(channels):
        ch = ET.SubElement(tv, "channel", {"id": f"qa.{idx}"})
        ET.SubElement(ch, "display-name").text = f"Qatar {idx}"
    for idx in range(live):
        t = now + timedelta(minutes=shift)
        end = now + timedelta(hours=horizon)
        number = 0
        while t < end:
            stop = min(t + timedelta(minutes=period), end)
            p = ET.SubElement(tv, "programme", {
                "channel": f"qa.{idx}",
                "start": t.strftime("%Y%m%d%H%M%S +0000"),
                "stop": stop.strftime("%Y%m%d%H%M%S +0000"),
            })
            ET.SubElement(p, "title", {"lang": "ar"}).text = (
                "" if idx == 0 and number < invalid_titles else
                f"برنامج موثق {idx}-{number}"
            )
            t = stop
            number += 1
    return ET.tostring(tv, encoding="utf-8", xml_declaration=True)


class TestLivePublication(unittest.TestCase):
    def setup_workspace(self, root, candidate, previous):
        root = Path(root)
        (root / "output/final").mkdir(parents=True)
        (root / "feeds").mkdir()
        (root / "output/final/tabie.xml.gz").write_bytes(gzip.compress(candidate))
        old = root / "feeds/tabie.xml.gz"
        old.write_bytes(gzip.compress(previous))
        old_meta = old.read_bytes()
        return old, old_meta

    def publish(self, root):
        process = subprocess.run(
            [sys.executable, str(PUBLISHER), "--source", "tabie",
             "--report", "reports/publish-test.json"],
            cwd=str(root), text=True, capture_output=True, timeout=25)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads((Path(root) / "reports/publish-test.json").read_text())
        return report["sources"]["tabie"]

    def test_real_12h_recovery_replaces_completely_expired_feed(self):
        with tempfile.TemporaryDirectory() as td:
            old, before = self.setup_workspace(
                td, timeline(), timeline(horizon=12, shift=-3*24*60))
            outcome = self.publish(td)
            self.assertTrue(outcome["published"], outcome)
            self.assertTrue(outcome["candidate_stats"]["partial_recovery_from_expired_lkg"])
            self.assertGreaterEqual(outcome["candidate_stats"]["current_channels"], 4)
            self.assertNotEqual(old.read_bytes(), before)

    def test_recovery_exemption_never_overwrites_current_lkg(self):
        with tempfile.TemporaryDirectory() as td:
            old, before = self.setup_workspace(
                td, timeline(), timeline(horizon=36))
            outcome = self.publish(td)
            self.assertFalse(outcome["published"], outcome)
            self.assertIn("future_horizon<24h", outcome["reasons"])
            self.assertEqual(old.read_bytes(), before)

    def test_recovery_exemption_rejects_a_future_only_schedule(self):
        with tempfile.TemporaryDirectory() as td:
            old, before = self.setup_workspace(
                td, timeline(shift=180, horizon=15),
                timeline(horizon=12, shift=-3*24*60))
            outcome = self.publish(td)
            self.assertFalse(outcome["published"], outcome)
            self.assertTrue(any("current_ratio<" in reason for reason in outcome["reasons"]))
            self.assertEqual(old.read_bytes(), before)

    def test_blank_title_never_publishes_to_receiver(self):
        with tempfile.TemporaryDirectory() as td:
            old, before = self.setup_workspace(
                td, timeline(invalid_titles=1),
                timeline(horizon=12, shift=-3*24*60))
            outcome = self.publish(td)
            self.assertFalse(outcome["published"])
            self.assertTrue(any("missing_title_rows" in x for x in outcome["reasons"]))
            self.assertEqual(old.read_bytes(), before)

    def test_packer_drops_only_blank_titles_without_faking_replacements(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            inp = path / "real.xml"
            inp.write_bytes(timeline(channels=1, live=1, horizon=1, invalid_titles=1))
            gz = path / "published.xml.gz"
            stats = path / "published.json"
            cmd = [
                sys.executable, str(PACKER), "--input", str(inp),
                "--output-gz", str(gz), "--output-txt", str(path / "feed.txt"),
                "--stats", str(stats), "--label", "synthetic", "--window-hours", "48",
            ]
            proc = subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=25)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            meta = json.loads(stats.read_text())
            root = ET.fromstring(gzip.decompress(gz.read_bytes()))
            self.assertEqual(meta["rejected_missing_title"], 1)
            self.assertEqual(meta["programmes"], 1)
            self.assertEqual(len(root.findall("programme")), 1)
            self.assertTrue(all((p.findtext("title") or "").strip()
                                for p in root.findall("programme")))
            self.assertEqual(meta["sha256"], hashlib.sha256(gz.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
