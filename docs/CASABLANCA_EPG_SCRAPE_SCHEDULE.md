# EPG Scrapers — Morocco / Casablanca source scrape schedule (18 October 2026)

Scope: **GitHub EPG source fetch and public XMLTV publication only**.
This does not change the Vu+ receiver, Enigma2 EPGImport schedule, mappings,
installed EPGManager RC79.1 or the blocked RC80 release.

## Source wall-clock schedule (Africa/Casablanca)

| Local clock | Workflow | Behavior |
| --- | --- | --- |
| **01:20 daily** | `refresh-elcinema.yml` | Sole scheduled ElCinema scraper |
| **01:40 daily** | `refresh-osn.yml` | Sole scheduled OSN scraper |
| **02:22 daily** | `refresh-bein.yml` | Sole scheduled beIN MENA scraper |
| **03:05 daily** | **`refresh-sport24.yml`** | **Sole scheduled Sport24 scraper** |
| **03:39 daily** | **`refresh-shahid.yml`** | **Sole scheduled Shahid / MBC scraper** |
| 07:15 daily | `daily-epg-chain.yml` | Al Jazeera → Dubai+ → STARZPLAY → Tunisia → STC → AlKass → Rotana → Morocco → Tabie; ElCinema donor *postprocess*, then one derived MENA rebuild. **No ElCinema, OSN, beIN, Sport24 or Shahid scraper** |
| 14:15 daily | `epg-watchdog.yml` | Freshness/accepted-LKG checks; may rebuild derived MENA only; **does not run source scrapers** |
| 19:30 daily | `epg-evening-casablanca.yml` | AlKass refresh only; no Sport24 retry |
| 20:30 daily | `epg-evening-casablanca.yml` | Morocco refresh |

The old `epg-casablanca-targeted-retry.yml` workflow **no longer has
an automatic 15:00 schedule**. It remains available using `workflow_dispatch`
for an explicitly requested, degraded **Shahid-only** manual retry. The
source-specific `refresh-shahid.yml` also retains manual dispatch, but not
an extra `push` trigger.

## Single scheduled Shahid refresh at 03:39

- Native GitHub Actions timezone-aware schedule:
  `cron: "39 3 * * *"`, `timezone: "Africa/Casablanca"`.
  Moroccan civil time is respected during DST/Ramadan changes; **never**
  hard-code a fixed UTC offset.
- It calls the existing `refresh-source-core.yml` with
  `source: shahid` and `scheduled: false` to bypass the shared
  legacy 06:00 time gate. The core still validates, checks source quality
  and preserves good last-known EPG (LKG) during failures.
- The 07:15 sequential chain contains neither Shahid nor Sport24.
  Rotana now depends directly on AlKass; all other source chains are preserved.
- The automatic 15:00 targeted retry is removed, not merely filtered.
  The optional manual retry still applies existing missing/stale/low-NOW
  coverage safeguards and refuses an active main chain.
- The legacy `daily-epg.yml`, `daily-source-refresh.yml`,
  `refresh-source-core.yml` and ElCinema donor utility have no
  direct scheduled scrape trigger. The watchdog rebuilds derived feeds
  only and does not re-scrape Shahid.
- Shared `epg-source-publish` concurrency remains unchanged. GitHub Actions
  can delay scheduled starts; a delayed 02:22 beIN or 01:40 OSN scrape
  may serialize the 03:05 Sport24 or 03:39 Shahid jobs. The listed times
  are **trigger times, not guaranteed start/completion times**.

## Validation / release safety

A read-only CI regression (`shahid-0339-schedule-ci.yml`) audits the
exact Shahid trigger, all known duplicate routes, the surrounding
ElCinema/OSN/beIN schedules, Moroccan time boundaries, and existing
workflow/policy tests on Python 3.13 and 3.14. The source schedule
becomes effective only after a tested PR merges into `main`.

A successful workflow review does not prove the next *live* 03:39
source grab will succeed: check its output, LKG acceptance and
actual GitHub Actions start after activation. No source guides,
translations, receiver installation or private backup are altered by
this schedule-only change.

## Sport24 sole scheduled daily scrape at 03:05

- Native GitHub Actions `schedule` uses `cron: "5 3 * * *"`, with
  `timezone: "Africa/Casablanca"` for Moroccan civil time throughout DST
  and Ramadan. Do not hardcode a UTC offset.
- `refresh-sport24.yml` calls the existing shared publisher using
  `source: sport24`, `scheduled: false`; manual dispatch remains available.
- Sport24 was removed from the 07:15 chain; Rotana now follows AlKass.
- The 19:30 sports workflow still refreshes AlKass, but its source matrix
  excludes Sport24. No other automatic Sport24 refresh is configured.
- **Coverage warning:** the direct Sport24 guide has historically provided
  only about 3–5 hours of future programmes. Changing its refresh cadence
  to once at 03:05 may leave native-only Sport24 channels without EPG later
  in the day. Genuine exact-channel OSN/Dubai+ supplementation currently
  covers just three Sport24 IDs, and is conditional on verified donor health.
  Zero-EPG Thmanyah 1/3 remain unchanged; no synthetic schedules permitted.
- Source LKG protection and signed receiver settings are unchanged. This
  does not schedule a Vu+ EPGImport run or install EPGManager R80.
- A read-only source-schedule regression (`sport24-0305-schedule-ci.yml`)
  must pass on Python 3.13 and 3.14 before the change is merged. Observe
  the next real 03:05 scraping run afterward to establish actual EPG updates.
