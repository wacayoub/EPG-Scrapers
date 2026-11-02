# EPG-Scrapers compatibility publications

All provider source code, schedules, validation and development now live in
[EPGManager](https://github.com/wacayoub/EPGManager).

This repository retains existing feeds/ and reports/ URLs for installed
receivers. Its only workflow mirrors verified publications from EPGManager
hourly, preserving actual provider timestamps and content. It does not scrape
providers or create programme schedules.

New integrations should use:

https://raw.githubusercontent.com/wacayoub/EPGManager/main/feeds/<source>.xml.gz

Legacy URLs remain available during receiver migration. Git history preserves
the former engine; its history was also merged into EPGManager.
