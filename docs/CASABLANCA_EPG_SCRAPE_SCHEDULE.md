# EPG-Scrapers — All source schedules on fixed GMT+0 (18 October 2026)

**Definition:** User explicitly requests **GMT+0 fixed clock**, not
`Africa/Casablanca` civil wall-clock. For scheduling, **GMT+0 equals
UTC+0**. The GitHub Actions native IANA timezone is now `Etc/GMT`
(fixed +00:00, no Moroccan/Ramadan/DST shifting). At present
(18 October 2026), Casablanca local civil time is GMT+1, so a
04:44 GMT+0 trigger appears as 05:44 in Casablanca.

This is a **GitHub source scraper schedule only**. It does not change
Vu+ / Enigma2 / EPGImport receiver scheduling, local receiver timezone,
installed EPGManager RC79.1, blocked R80, or private mappings.

## The effective automatic schedule

| Fixed GMT+0 trigger | Action | Workflow |
| --- | --- | --- |
| **01:20 daily** | ElCinema — one source scrape | `refresh-elcinema.yml` |
| **01:40 daily** | OSN — one source scrape | `refresh-osn.yml` |
| **02:22 daily** | beIN MENA — one source scrape | `refresh-bein.yml` |
| **03:05 daily** | Sport24 — one source scrape | `refresh-sport24.yml` |
| **03:39 daily** | Shahid/MBC — one source scrape | `refresh-shahid.yml` |
| **04:12 daily** | **Al Jazeera / Al Jazeera English — one source scrape** | **`refresh-aljazeera.yml`** |
| **04:44 daily** | Dubai+ — one source scrape | `refresh-dubaiplus.yml` |
| **07:15 daily** | Other sequential sources: STARZPLAY → Tunisia TV → STC → AlKass → Rotana → Morocco → Tabie; then ElCinema donor postprocess and derived MENA rebuild | `daily-epg-chain.yml` |
| **14:15 daily** | Watchdog health checks; may rebuild derived MENA only, does not source-scrape | `epg-watchdog.yml` |
| **19:30 daily** | AlKass only, extra evening sport guide | `epg-evening-casablanca.yml` |
| **20:30 daily** | Morocco evening refresh | `epg-evening-casablanca.yml` |

All automatic `schedule` entries above specify exactly
`timezone: "Etc/GMT"`. A `cron: "44 4 * * *"` with `Etc/GMT`
always targets 04:44 GMT+0, including when Morocco changes legal UTC offset.
Execution on GitHub may be delayed by queueing or shared
`epg-source-publish` concurrency. **Cron time is a trigger target,
not an exact guaranteed completion time**.

## Duplicate source protections

- Dubai+ dedicated daily 04:44 is the **sole automatic Dubai+ scraper**.
  Remove the 07:15 `dubaiplus` chain job; STARZPLAY remains in
  the 07:15 chain, now as its first job. Remove the former Dubai+ `push` trigger for
  `config/dubaiplus-refresh-trigger.txt`; keep `workflow_dispatch`.
- ElCinema, OSN, beIN, Sport24, Shahid and Al Jazeera each have their
  sole dedicated automatic daily cron; no 07:15 duplicates.
- Al Jazeera's dedicated schedule is `12 4 * * *` at `Etc/GMT`:
  **04:12 fixed GMT+0**, no seasonal shift. Remove its old 07:15
  upstream job and make STARZPLAY the first source in the remaining chain.
  Keep `workflow_dispatch` for deliberate manual Al Jazeera refreshes.
- Sport24 remains removed from evening 19:30: only AlKass is re-scraped.
- Shahid targeted retry is still **manual only**, with no automatic 15:00.
- The shared legacy `refresh-source-core.yml` "06:00 scheduled" guard
  has also been moved to fixed GMT+0. Normal dedicated source workflows
  pass `scheduled: false` and keep publisher integrity checks.
- Other `workflow_dispatch` and explicitly configured `push` triggers
  are on-demand/event-based, **not** additional daily clock schedules.
  No source item is manufactured by schedule changes.

## Dubai+ EPG quality and caveats

At last audited publication (2026-10-17 10:51 UTC/GMT), 9/9 Dubai+
channels carried guides with 423 programmes and a ~48h horizon.
Dubai One has a genuine 185-minute internal gap, Dubai TV 120 minutes,
and Dubai Zaman 180 minutes. **350 of 413 future programmes lacked
authentic descriptions**. The separate Dubai+ quality PR adds support
for native ar-AE provider-localized synopsis fields but does not invent
any missing descriptions or fill unrelated channel gaps.

Only DubaiTV.ae@SD may be complemented by the strict exact-ID OSN
48h PASS genuine donor, preserving all Dubai+ primary programmes.
Sport24's three exact sports donors remain independent.

## Acceptance

Regress `gmt0-all-sources-0444-ci.yml` on both Python 3.13 and 3.14,
in addition to the pre-existing per-source schedule checks. Confirm the
fixed GMT+0 offset even on winter, summer and Ramadan examples.

**After merge**, first 04:44 GMT+0 Dubai+ source run is not yet proof
of health until actual publication/LKG/guide audit is observed. Nothing
in this change installs or edits anything on the receiver.
