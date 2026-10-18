# EPG Scrapers: Casablanca wall-clock schedule (18 October 2026)

This schedule applies to GitHub public XMLTV fetching and publication, not the
Vu+ receiver or its local EPGImport / installed EPGManager.

| Casablanca time | Workflow | Scraping behavior |
| --- | --- | --- |
| 01:20 daily | `refresh-elcinema.yml` | Only ElCinema source scraper |
| **01:40 daily** | **`refresh-osn.yml`** | **Only OSN source scraper** |
| 02:22 daily | `refresh-bein.yml` | Only beIN MENA source scraper |
| 07:15 daily | `daily-epg-chain.yml` | Sequential Al Jazeera → Dubai+ → STARZPLAY → Tunisia → STC → AlKass → Shahid → Sport24 → Rotana → Morocco → Tabie; followed by ElCinema *donor postprocess* and MENA derived rebuild. No OSN, ElCinema or beIN scraper |
| 14:15 daily | `epg-watchdog.yml` | Checks freshness; may rebuild derived MENA, never re-scrapes OSN |
| 15:00 daily | `epg-casablanca-targeted-retry.yml` | Retry **Shahid only** if degraded; never retry OSN, ElCinema or beIN |
| 19:30 daily | `epg-evening-casablanca.yml` | Sport24 and AlKass only |
| 20:30 daily | `epg-evening-casablanca.yml` | Morocco only |

## OSN one-scheduled-trigger policy

- One native timezone-aware GitHub Actions `schedule` trigger at `40 1 * * *`
  with `timezone: Africa/Casablanca`. It preserves 01:40 local wall-clock
  through normal Moroccan DST / Ramadan changes; do not hardcode UTC+1.
- `refresh-osn.yml` delegates to the existing `refresh-source-core.yml`
  with `source: osn` and `scheduled: false` so the legacy 06:00-only
  time gate does not reject this dedicated schedule.
- The OSN job is **absent** from the 07:15 sequential chain. The next
  `dubaiplus` step now depends directly on `aljazeera`.
- The 15:00 target policy has `TARGETS = ("shahid",)`; even a missing or
  rejected OSN LKG cannot cause a second automatic scrape.
- The OSN workflow has no `push` trigger. Its `workflow_dispatch` remains
  available for deliberately requested manual execution; this is not a
  second automatic schedule.
- Legacy `daily-epg.yml`, `daily-source-refresh.yml`,
  `elcinema-daily-donors.yml` and `refresh-source-core.yml` have
  **no schedule** of their own. The watchdog and derived-feed rebuild
  do not scrape OSN.
- Provider publisher concurrency (`epg-source-publish`) and source
  LKG/quality checks remain unchanged. GitHub Actions may start a
  scheduled job late or serialize it behind the 01:20 ElCinema job:
  **01:40 is the requested trigger time, not a guaranteed start time**.

## Safety and acceptance

The change modifies only the GitHub source automation and its test/docs.
It does not modify Enigma2, the Vu+ receiver, private mappings, the
existing RC79.1 plugin, the receiver's EPGImport schedule, the built XMLTV,
`update.json`, or any installable R80 package.

Validate the exact workflow YAML using the read-only
`osn-0140-schedule-ci.yml` regression on Python 3.13 and 3.14 before
merging. After merge, the first daily OSN execution and its LKG/publication
result still need observation: an accepted publish, source errors, and
GitHub scheduling latency cannot be predicted from static tests.
