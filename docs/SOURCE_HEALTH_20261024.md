# Source and scraping qualification — 24 October 2026

This is a pinned main snapshot audit at commit
233ce53601121d95b0dd06710769b392b6883204. It does not install anything on the
receiver or publish new XMLTV data. [Aggregate evidence](evidence/source-health-20261024.json).

## Reproduced defects and corrections

The all-source auditor previously copied `no_future_epg_ids` from a report made
at publication time. At the actual check, Morocco had 10 missing IDs versus
the reported nine, beIN 26 versus one and Sport24 six versus four. Time passing
can expire real schedules while their old SHA/cohort remain perfectly valid.
The auditor now parses bounded, SHA-verified gzip XMLTV at the check time,
counts current/future events by exact channel ID, and rejects invalid times,
empty titles, orphan programmes, duplicate channel IDs or metadata count drift.
An unspecified timezone is not accepted as current programme evidence.
Original publication report counts remain separately labelled `reported_*`.

The old three-channel STC scope warning contradicted the current complete
149-channel adapter. Remove that obsolete cap; actual XMLTV/manifest catalogue
counts and individual quality warnings remain checked. No channel is deleted.

MENA still incorporated the previous Tabie, OSN and ElCinema source SHA values,
despite successful newer source workflows. The current readiness audit returns
`MENA_SOURCE_SNAPSHOT_OUTDATED`. A fixed daily orchestration time alone cannot
incorporate publications delayed beyond that time. Wire the 14 successful
main-branch source workflow completions to the existing derived-only rebuild.
Do not rescrape sources. Verify the accepted source snapshot and skip unchanged
byte snapshots; fail on missing/unaccepted sources. Keep the serialized rebuild,
trusted main checkout, SHA/cohort/routing gates and rebase/retry publication.
No artifact or code from the upstream run is downloaded or executed.

Correct three obsolete Casablanca/DST comments to fixed GMT+0, matching the
existing cron expressions. Cron times, receiver slot and programme times do not
change. GitHub schedule start delays remain observable operational constraints.

## Actual verification

- All 14 published gzip SHA/size and channel/programme counts match metadata.
  No empty programme title or invalid timestamp in these source payloads.
- Local MENA rebuild from those actual 14 source bytes: 516 IDs and 31,526
  programmes, versus 30,778 in the published derived snapshot. All 14 SHA match,
  zero structural errors; 329 qualified, 138 degraded, 49 without future EPG.
  These outputs remain local, not publicly published. The 49 are not recovered
  guides and must never be represented as reliable Best Match candidates.
- Real, bounded Morocco scrape completed locally: 329 programmes across five
  IDs (2M 64, Al Aoula 77, Assadisa 104, Medi1 Arabic 45, Medi1 Maghreb 39).
  SNRT is partially reachable from this PC; Arryadia and several SNRT IDs are
  still missing. Chada returned only five already-expired rows and no tomorrow
  rows, so no Chada programme was published in this candidate. No dates were
  shifted and no replacement broadcasts were invented. Nine 2M titles remain
  untranslated; the group remains explicitly degraded.
- Workstation Python 3.13.2: 190 baseline tests and 204 corrected tests PASS.
  New tests cover publication-pass/future-expiry divergence, UTC offsets,
  malformed/oversized payloads, identity/count drift, stale derived snapshots,
  failed source integrity and all 14 completion trigger names/default-branch
  restrictions. GitHub Python 3.13/3.14 CI is recorded in the PR separately.

The first PR CI run reproduced the known published-snapshot failure. Candidate
CI now diagnoses that baseline separately (only snapshot lag may be a warning;
every other structural defect blocks), reconstructs the derived candidate in
the disposable read-only-permission checkout, then requires all original strict
structural/SHA/catalogue assertions to pass. The real production release gate
still rejects every structural error before any commit/push. The baseline,
candidate and production-order CI scripts also executed locally and passed.

## Scope and remaining work

The latest sampled source workflows succeeded; older sequential-chain failures
do not prove a current source failure. A green workflow still does not imply
complete programmes. Nineteen OSN Legacy/Other IDs remain empty, other guides
are partial or expired, and flagged repetitive titles require actual provider
verification. Do not silently substitute similar channel names or invent guides.

GO for review of the code corrections. NO GO for claiming every scraper/guide
is repaired. The new workflow_run path requires merge/default-branch deployment
and an observed real source completion before production qualification. The
existing qualified receiver package remains untouched.
