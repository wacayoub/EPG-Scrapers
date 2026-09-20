# Arab fallback final analysis

Active fallback rows: **1534**  
Zero-EPG IDs blacklisted: **931**  
Canonical groups: **1280**  
Duplicate groups: **210**  
Extra duplicate rows collapsed: **254**  
New IDs after zero/LatAm filtering: **1309**

## Source blacklist

| Provider | Source | Reason | Detail |
|---|---|---|---|
| epgshare | EG1 | ZERO_ACTIVE_CHANNELS | 238 channels, 0 active |
| epgshare | SA1 | ZERO_ACTIVE_CHANNELS | 97 channels, 0 active |
| openepg | arabiapremiumar | INVALID_SOURCE_XML | no element found: line 1, column 0 |

## Integration rule

Healthy direct sources are never replaced. Fallback winners are only candidates for channels that still have zero EPG. Duplicate alternatives remain available as failover; zero-programme IDs stay dynamically blacklisted until they recover future programmes.
