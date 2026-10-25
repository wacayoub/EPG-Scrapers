"""Decide from exact accepted source bytes, never scrape or publish anything."""
import argparse
import hashlib
import json
from pathlib import Path

try:
    from mena_source_snapshot import get_source_snapshot, needs_rebuild
except ImportError:
    from tools.mena_source_snapshot import get_source_snapshot, needs_rebuild


def required(root):
    root = Path(root)
    policy = json.loads((root/'config/canonical-channel-policy.json').read_text(encoding='utf-8'))
    snapshot = get_source_snapshot(root/'feeds', policy['default_source_order'])
    if not snapshot or any(value is None for value in snapshot.values()):
        raise ValueError('MISSING_ACCEPTED_SOURCE')
    metadata = root/'feeds/mena.json'
    feed = root/'feeds/mena.xml.gz'
    if not metadata.is_file() or not feed.is_file():
        return True
    meta = json.loads(metadata.read_text(encoding='utf-8'))
    data = feed.read_bytes()
    if meta.get('sha256') != hashlib.sha256(data).hexdigest() or meta.get('size_bytes') != len(data):
        return True
    return needs_rebuild(snapshot, meta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    changed = required(args.root)
    print('MENA_REBUILD_REQUIRED' if changed else 'MENA_SOURCE_SNAPSHOT_UNCHANGED')
    return 0 if changed else 10


if __name__ == '__main__':
    raise SystemExit(main())
