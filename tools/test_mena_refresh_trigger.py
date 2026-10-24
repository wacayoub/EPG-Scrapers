"""Source completion must refresh a stale derived feed, without scraping twice."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import yaml
from tools.mena_rebuild_required import required

REPO=Path(__file__).resolve().parents[1]


class RefreshDecision(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'feeds').mkdir();(self.root/'config').mkdir()
        (self.root/'config/canonical-channel-policy.json').write_text(
            json.dumps({'default_source_order':['osn','tabie']}))
        self.snapshot={}
        for name in ('osn','tabie','mena'):
            data=b'\x1f\x8b'+name.encode()
            (self.root/f'feeds/{name}.xml.gz').write_bytes(data)
            digest=hashlib.sha256(data).hexdigest()
            self.snapshot[name]=digest
            (self.root/f'feeds/{name}.json').write_text(json.dumps(
                {'sha256':digest,'size_bytes':len(data)}))
        p=self.root/'feeds/mena.json';meta=json.loads(p.read_text())
        meta['source_snapshot']={k:v for k,v in self.snapshot.items() if k!='mena'}
        p.write_text(json.dumps(meta))

    def test_unchanged_verified_snapshots_skip_extra_publication(self):
        self.assertFalse(required(self.root))

    def test_one_new_accepted_source_rebuilds_with_unrelated_old_sources(self):
        data=b'\x1f\x8bnew osn source'
        (self.root/'feeds/osn.xml.gz').write_bytes(data)
        (self.root/'feeds/osn.json').write_text(json.dumps(
            {'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}))
        self.assertTrue(required(self.root))

    def test_unaccepted_source_bytes_fail_instead_of_triggering_publication(self):
        (self.root/'feeds/osn.xml.gz').write_bytes(b'\x1f\x8bunaccepted')
        with self.assertRaisesRegex(ValueError,'SHA_OR_SIZE_MISMATCH'):
            required(self.root)

    def test_missing_source_fails_even_if_derived_metadata_agrees(self):
        (self.root/'feeds/tabie.xml.gz').unlink()
        with self.assertRaisesRegex(ValueError,'MISSING_ACCEPTED_SOURCE'):
            required(self.root)

    def test_missing_or_corrupted_derived_payload_requires_rebuild(self):
        (self.root/'feeds/mena.xml.gz').write_bytes(b'changed')
        self.assertTrue(required(self.root))
        (self.root/'feeds/mena.xml.gz').unlink()
        self.assertTrue(required(self.root))


class WorkflowContract(unittest.TestCase):
    def test_all_fourteen_source_completions_are_wired_once(self):
        workflow=yaml.safe_load((REPO/'.github/workflows/rebuild-mena-derived.yml').read_text())
        events=workflow.get('on',workflow.get(True))
        trigger=events['workflow_run']
        sources=['morocco','bein','osn','elcinema','starzplay','stctv','shahid',
                 'dubaiplus','sport24','rotana','aljazeera','alkass','tabie','tunisiatv']
        names=[yaml.safe_load((REPO/f'.github/workflows/refresh-{s}.yml').read_text())['name'] for s in sources]
        self.assertEqual(set(trigger['workflows']),set(names))
        self.assertEqual(len(trigger['workflows']),14)
        self.assertEqual(trigger['branches'],['main'])
        self.assertEqual(trigger['types'],['completed'])
        job=workflow['jobs']['rebuild']
        self.assertIn("conclusion == 'success'",job['if'])
        checkout=next(s for s in job['steps'] if s.get('uses','').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['ref'],'main')
        self.assertNotIn(workflow['name'],trigger['workflows'])
        commands='\n'.join(s.get('run','') for s in job['steps'])
        self.assertIn('mena_rebuild_required.py',commands)
        self.assertNotIn('refresh_one_source.sh',commands)


if __name__=='__main__':
    unittest.main()
