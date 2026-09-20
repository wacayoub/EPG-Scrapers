# EPG-Scrapers

Production XMLTV scrapers for MENA channels.

## Sources
- `morocco`: Morocco/2M/SNRT adapters
- `elcinema`: Arabic entertainment channels
- `bein`: beIN MENA
- `osn`: OSN
- `sport24`: sports fallback/auxiliary source

## Safety rules
Each source is scraped independently. A candidate feed is validated before publication. If validation fails, the previous known-good `.xml.gz` remains untouched.

Validation includes:
- valid XMLTV
- unique channel IDs
- `start < stop`
- no exact duplicate programme rows
- minimum future programmes
- gzip integrity
- per-channel zero-EPG and future-zero monitoring

## Schedule
GitHub Actions runs once per day at **06:00 Africa/Casablanca**. Because GitHub cron is UTC, the workflow runs at 05:00 UTC during Morocco UTC+1 periods and contains a timezone guard so publication only happens at local 06:00. It can also be run manually.

## Outputs
- `feeds/<source>.xml.gz`
- `reports/latest.json`
- `reports/latest.md`

The repository is designed so EPGManager/Vu+ can consume each source independently.
