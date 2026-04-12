# DH Digest — Project Context Prompt

Use this prompt to give Claude full context when making future updates to this project.

---

## Prompt (copy everything below this line)

I have a working Python project called **dh-digest** hosted at `https://github.com/MRothy/dh-digest`. It sends a weekly HTML email digest of Digital Humanities RSS feeds and scraped websites. Here is the full context:

---

### What it does
- Fetches new posts from 10 RSS feeds using `feedparser`
- Scrapes 2 websites without RSS feeds using `requests` and `BeautifulSoup`
- Deduplicates against `seen_items.json` (SHA-256 hash of URL + title, truncated to 16 chars)
- Builds a clean HTML email grouped by source category with inline CSS
- Sends via Gmail SMTP using an App Password (not OAuth)
- Updates `seen_items.json` only after a successful send
- Runs automatically every Monday at 8am UTC via GitHub Actions, and can be triggered manually

---

### Project structure
```
dh-digest/
├── digest.py                          # main script
├── seen_items.json                    # persists sent item hashes
├── requirements.txt                   # feedparser, requests, beautifulsoup4, python-dotenv, langdetect
├── .env                               # local only — GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL
├── .gitignore                         # excludes .env
└── .github/
    └── workflows/
        └── weekly_digest.yml          # GitHub Actions cron workflow
```

---

### RSS feeds (10 total)
```python
RSS_FEEDS = [
    # Aggregators & News
    {"name": "Digital Humanities Now",           "url": "https://digitalhumanitiesnow.org/feed/",            "category": "Aggregators & News"},
    {"name": "The Signal (Library of Congress)", "url": "https://blogs.loc.gov/thesignal/feed/",             "category": "Aggregators & News"},
    {"name": "DH+Lib",                           "url": "https://dhandlib.org/?feed=rss2",                   "category": "Aggregators & News"},
    # Tutorials & Methods
    {"name": "Programming Historian",            "url": "https://programminghistorian.org/en/feed.xml",         "category": "Tutorials & Methods"},
    {"name": "Reviews in Digital Humanities",    "url": "https://reviewsindh.pubpub.org/rss.xml",            "category": "Tutorials & Methods"},
    # Professional Orgs
    # ACH News removed 2026-03-25 — https://ach.org/news/feed/ returns 404; no working feed URL found
    {"name": "The Stoa",                         "url": "https://blog.stoa.org/feed",                        "category": "Professional Orgs"},
    # Institutional Blogs
    {"name": "Sussex Humanities Lab",            "url": "https://sussexhumanitieslab.wordpress.com/feed/",   "category": "Institutional Blogs"},
    # DH at Glasgow removed 2026-03-25 — connection refused (server unreachable)
    # MITH removed 2026-03-25 — redirects to dead 404 archive path (site under redevelopment)
    # Scholar Blogs
    {"name": "Kathleen Fitzpatrick",             "url": "https://kfitz.info/feed/feed.xml",                  "category": "Scholar Blogs"},
    {"name": "Andrew Goldstone",                 "url": "https://andrewgoldstone.com/index.xml",             "category": "Scholar Blogs"},
    {"name": "Matthew Lincoln",                  "url": "https://matthewlincoln.net/feed.xml",               "category": "Scholar Blogs"},
]
```

### Scraped sites (2 total, each has its own named scraper function)
```python
SCRAPE_TARGETS = [
    {"name": "Stanford Digital Humanities", "url": "https://digitalhumanities.stanford.edu/", "category": "Institutional Blogs"},
    {"name": "HASTAC",                      "url": "https://www.hastac.org/blog",             "category": "Aggregators & News"},
]
```
Scrapers are registered in a `SCRAPER_MAP` dict — adding a new scraper means writing a function and adding one line to the map.

---

### Key implementation details
- **Python version:** 3.14 (local), 3.12 (GitHub Actions)
- **Date formatting:** uses a `_fmt_date()` helper for cross-platform compatibility (`%-d` on Linux, `%#d` on Windows)
- **Lookback window:** `LOOKBACK_DAYS = 7` — items older than 7 days are skipped
- **Category display order:** Aggregators & News → Tutorials & Methods → Professional Orgs → Institutional Blogs → Scholar Blogs
- **Email:** `multipart/alternative` with both HTML (inline CSS only) and plain text parts; sent via `smtplib.SMTP_SSL` on port 465
- **Zero items:** exits cleanly with a log message, no email sent, `seen_items.json` not touched
- **Feed errors:** logged and skipped per-feed — one bad feed never aborts the run
- **Language filtering:** English-only filtering is active via `langdetect`. Each item's title is checked with `_is_english()` before deduplication; non-English items are skipped and logged at INFO level. Detection failures (LangDetectException) are treated as English (fail-open) to avoid discarding items when detection is uncertain.
- **`seen_items.json`** is committed back to the repo by the GitHub Actions workflow after each successful send using `[skip ci]` to prevent a loop

---

### Environment variables
| Variable | Description |
|---|---|
| `GMAIL_USER` | Sender Gmail address |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password |
| `RECIPIENT_EMAIL` | Recipient address |

Set in `.env` locally, and as GitHub Actions repository secrets for CI.

---

### GitHub Actions workflow highlights
- Trigger: `cron: '0 8 * * 1'` (Mondays 8am UTC) + `workflow_dispatch`
- Uses `actions/setup-python@v5` with `cache: 'pip'`
- After a successful run, commits updated `seen_items.json` back to `main`

---

### Removed feeds (verified dead as of 2026-03-25)
- **ACH News** — `https://ach.org/news/feed/` returns 404; no working feed found at any standard path
- **DH at Glasgow** — `https://digitalhumanities.glasgow.ac.uk/feed/` connection refused (server unreachable)
- **MITH** — `https://mith.umd.edu/news/feed/` redirects to `archive.mith.umd.edu` which also 404s; site is under redevelopment

### Known feed quirks (warnings only, not errors)
- **Kathleen Fitzpatrick** — feed URL is `https://kfitz.info/feed/feed.xml` (the bare `/feed/` path serves an HTML directory listing)

---

### Recent changes (2026-04-11)
- **English-language filtering added** — `langdetect==1.0.9` added to `requirements.txt`. New `_is_english(text)` helper in `digest.py` calls `detect()` on each item title before deduplication. Returns `True` (fail-open) on `LangDetectException`. Non-English items are skipped with an `INFO`-level log message. Applied in all three item-collection paths: `fetch_rss_items`, `_scrape_stanford`, `_scrape_hastac`.
- **Programming Historian feed switched to English-only URL** — changed from `https://programminghistorian.org/feed.xml` to `https://programminghistorian.org/en/feed.xml` to filter at the source rather than relying on langdetect.

---

Now here is what I'd like to update: [DESCRIBE YOUR CHANGE HERE]

