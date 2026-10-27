# CTI Radar

A dashboard that collects RSS/Atom feeds from threat intelligence vendor blogs and security news sites in one place.
The server fetches the feeds on a schedule, and an open page picks up new items every minute.

## Running

Requires only Python 3.9+, no extra packages.

```bash
python3 server.py              # http://localhost:8080
python3 server.py --port 9000  # different port
```

With Docker:

```bash
docker build -t cti-radar .
docker run -d -p 8080:8080 --name cti-radar cti-radar
```

## Features

- **Stream** view: a single timeline of all sources, grouped by day.
- **Board** view: one card per source with its latest 7 posts; unreachable sources show the error.
- Clicking a title opens the post in a new tab and marks it as read.
- Items that arrived since your last visit get a **NEW** tag.
- Filter by type (News / CTI blogs / Advisories), time range and source; search titles and summaries.
- **Refresh now** rescans every source without waiting for the next scheduled run.
- Filters, read state and the selected view are kept in the browser.
- Items are saved to `cache.json`, so a restarted server opens with the previous data.

## Adding or removing sources

Edit `feeds.json`. Changes apply on the next scan (or on **Refresh now**); no restart needed.

```json
{ "name": "Source name", "url": "https://example.com/feed/", "category": "cti" }
```

`category` can be `news`, `cti` or `advisory`.
`refresh_minutes` sets the scan interval (default 15), and `max_items_per_feed` sets how many entries to keep per source.

A red dot next to a source in the sidebar means it could not be reached; hover over it to see why.
The feed URL may have changed: find the site's current RSS link and update it in `feeds.json`.
