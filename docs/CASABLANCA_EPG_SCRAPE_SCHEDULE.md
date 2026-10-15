# Casablanca EPG scraping schedule (October 2026)

Scope: public GitHub source fetch / publication only. The Vu+ Zero 4K
installation, RC79.1 mappings, EPG cache, settings, and 21:30 receiver-side
EPGImport are **not** modified by these workflows.

## Wall-clock schedule (IANA Africa/Casablanca)

| Clock time | Workflow | Behavior |
| --- | --- | --- |
| 07:15 | daily-epg-chain.yml | All 14 providers in sequence, then one derived MENA rebuild |
| 14:15 | epg-watchdog.yml | Check source ages / accepted LKG and rebuild MENA if sources are fresh but derived guide is old. **No full-chain retry.** |
| 15:00 | epg-casablanca-targeted-retry.yml | Retry ElCinema/OSN/beIN/Shahid **only** if source not generated today, LKG candidate rejected today, or less than 60% of active IDs had a genuine current programme at publication. Limit 4. Do not use strict 48h FAIL by itself. Skip if main chain is still active or GitHub API unavailable; late scheduled start after 19:00 skips. Rebuild MENA once only after successful actual retries. |
| 19:30 | epg-evening-casablanca.yml | Recheck beIN, Sport24 and AlKass sports/event sources only, then one derived rebuild |
| 20:30 | epg-evening-casablanca.yml | Recheck Morocco (especially Arryadia evening match changes), then one derived rebuild |

Schedules now use GitHub Actions' supported native timezone field
("Africa/Casablanca") instead of assuming UTC+1, so Moroccan Ramadan
time changes do not change the requested *local* hour.

## Important limits and protections

- GitHub Actions scheduled jobs can run **much later** than the specified cron.
  On 15 Oct 2026 the previous 06:07 UTC full-chain job actually started
  at 11:20:40 UTC, and the 09:37 UTC watchdog began at 14:21:55 UTC.
  Scheduled times are goals, not verified start-time guarantees.
- The core provider publisher retains its original epg-source-publish
  concurrency lock, provider-specific LKG freshness/regression checks, and
  no-invented-programmes policy.
- Any late evening scheduled event arriving outside 18:00–23:59 local skips
  instead of unexpectedly scraping the following morning.
- Running a manual dispatch is still supported and bypasses the evening
  scheduled-time gate, but not source publishing protections.
- Tabie/QMC provider returning the wrong day is an upstream issue; repeatedly
  scraping it at 15:00 does not repair dates. It remains on the main chain with
  LKG fallback until a real programme schedule is available.
- The user's *receiver-local* 21:30 EPG import is not configured from GitHub
  and must be treated as a separate device-side action. No SSH/VuLink, opkg,
  Enigma2 restart, or public upload of a private receiver backup occurs here.
- This change **does not** complete RC80 GUI/runtime or rollback testing.

## Validation

Before release, both Python 3.13 and 3.14 ran the metadata decision and YAML
tests, and current actionlint verified the four GitHub workflow definitions.
A public repository schedule becomes active when merged to the default branch.
After activation, inspect at least a full local day of workflow runs, their
actual created_at and started_at, the candidate publisher decisions and
freshness on feeds/*.json, plus MENA derived build status.
