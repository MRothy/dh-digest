"""
DH Digest — weekly HTML email digest of Digital Humanities RSS feeds and scraped sites.

Usage:
    python digest.py

Environment variables (set in .env or GitHub Actions secrets):
    GMAIL_USER          — sender Gmail address
    GMAIL_APP_PASSWORD  — Gmail App Password (not your regular password)
    RECIPIENT_EMAIL     — recipient address (can be same as GMAIL_USER)
"""

import os
import json
import hashlib
import logging
import smtplib
import textwrap
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import warnings

import feedparser
import requests
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Load environment ──────────────────────────────────────────────────────────
load_dotenv()

GMAIL_USER        = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL   = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)

SEEN_ITEMS_PATH = Path(__file__).parent / "seen_items.json"

# ── Feed / scrape configuration ───────────────────────────────────────────────
RSS_FEEDS = [
    # Aggregators & News
    {"name": "Digital Humanities Now",       "url": "https://digitalhumanitiesnow.org/feed/",            "category": "Aggregators & News"},
    {"name": "The Signal (Library of Congress)", "url": "https://blogs.loc.gov/thesignal/feed/",         "category": "Aggregators & News"},
    {"name": "DH+Lib",                       "url": "https://dhandlib.org/?feed=rss2",                   "category": "Aggregators & News"},
    # Tutorials & Methods
    {"name": "Programming Historian",        "url": "https://programminghistorian.org/feed.xml",          "category": "Tutorials & Methods"},
    {"name": "Reviews in Digital Humanities","url": "https://reviewsindh.pubpub.org/rss.xml",             "category": "Tutorials & Methods"},
    # Professional Orgs
    # ACH News removed 2026-03-25 — https://ach.org/news/feed/ returns 404; no working feed URL found
    {"name": "The Stoa",                     "url": "https://blog.stoa.org/feed",                        "category": "Professional Orgs"},
    # Institutional Blogs
    {"name": "Sussex Humanities Lab",        "url": "https://sussexhumanitieslab.wordpress.com/feed/",   "category": "Institutional Blogs"},
    # DH at Glasgow removed 2026-03-25 — https://digitalhumanities.glasgow.ac.uk/feed/ connection refused (server unreachable)
    # MITH removed 2026-03-25 — https://mith.umd.edu/news/feed/ redirects to dead 404 archive path (site under redevelopment)
    # Scholar Blogs
    {"name": "Kathleen Fitzpatrick",         "url": "https://kfitz.info/feed/feed.xml",                  "category": "Scholar Blogs"},
    {"name": "Andrew Goldstone",             "url": "https://andrewgoldstone.com/index.xml",              "category": "Scholar Blogs"},
    {"name": "Matthew Lincoln",              "url": "https://matthewlincoln.net/feed.xml",                "category": "Scholar Blogs"},
]

SCRAPE_TARGETS = [
    {"name": "Stanford Digital Humanities", "url": "https://digitalhumanities.stanford.edu/", "category": "Institutional Blogs"},
    {"name": "HASTAC",                      "url": "https://www.hastac.org/blog",             "category": "Aggregators & News"},
]

# How many days back to include items from (7 = past week)
LOOKBACK_DAYS = 7

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DH-Digest-Bot/1.0; "
        "+https://github.com/your-username/dh-digest)"
    )
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_date(dt: datetime, fmt: str) -> str:
    """strftime with cross-platform no-pad day: %-d on Linux, %#d on Windows."""
    if os.name == "nt":
        fmt = fmt.replace("%-d", "%#d")
    return dt.strftime(fmt)


# ─────────────────────────────────────────────────────────────────────────────
# Seen-items helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_ITEMS_PATH.exists():
        with open(SEEN_ITEMS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set) -> None:
    with open(SEEN_ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def item_id(url: str, title: str) -> str:
    """Stable hash used as a deduplication key."""
    raw = f"{url}|{title}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# RSS fetching
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(entry) -> datetime | None:
    """Return a timezone-aware datetime from a feedparser entry, or None."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def fetch_rss_items(feed_cfg: dict, seen: set, cutoff: datetime) -> list[dict]:
    """Fetch and filter new items from a single RSS feed."""
    name = feed_cfg["name"]
    url  = feed_cfg["url"]
    cat  = feed_cfg["category"]
    items = []

    try:
        parsed = feedparser.parse(url, request_headers=HEADERS)
        if parsed.bozo and parsed.bozo_exception:
            # bozo can fire for minor XML issues — log but still try entries
            log.warning("%s — feed parser warning: %s", name, parsed.bozo_exception)

        for entry in parsed.entries:
            link  = getattr(entry, "link",  "") or ""
            title = getattr(entry, "title", "") or "(no title)"
            uid   = item_id(link, title)

            if uid in seen:
                continue

            pub_date = _parse_date(entry)
            if pub_date and pub_date < cutoff:
                continue  # too old

            # Extract a short description / summary
            summary = ""
            for attr in ("summary", "description", "content"):
                raw = getattr(entry, attr, None)
                if raw:
                    if isinstance(raw, list):
                        raw = raw[0].get("value", "")
                    soup = BeautifulSoup(raw, "html.parser")
                    text = soup.get_text(" ", strip=True)
                    summary = textwrap.shorten(text, width=200, placeholder="…")
                    break

            items.append({
                "uid":     uid,
                "title":   title,
                "link":    link,
                "source":  name,
                "category": cat,
                "date":    _fmt_date(pub_date, "%b %-d, %Y") if pub_date else "",
                "summary": summary,
            })

        log.info("%-35s  %d new item(s)", name, len(items))

    except Exception as exc:
        log.error("%-35s  FAILED: %s", name, exc)

    return items


# ─────────────────────────────────────────────────────────────────────────────
# Web scraping
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_stanford(target: dict, seen: set) -> list[dict]:
    """Scrape Stanford DH news/blog listing page."""
    items = []
    resp = requests.get(target["url"], headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Stanford DH uses article cards with <h2>/<h3> headings inside <article> tags.
    for article in soup.select("article")[:10]:
        a_tag = article.find("a", href=True)
        if not a_tag:
            continue
        link  = a_tag["href"]
        if not link.startswith("http"):
            link = "https://digitalhumanities.stanford.edu" + link
        title = a_tag.get_text(strip=True) or article.find(["h2", "h3"]) and article.find(["h2", "h3"]).get_text(strip=True) or "(no title)"
        uid   = item_id(link, title)
        if uid in seen:
            continue

        # Try to grab a blurb
        blurb_tag = article.find("p")
        summary = textwrap.shorten(blurb_tag.get_text(" ", strip=True), 200, placeholder="…") if blurb_tag else ""

        items.append({
            "uid":      uid,
            "title":    title,
            "link":     link,
            "source":   target["name"],
            "category": target["category"],
            "date":     "",
            "summary":  summary,
        })
    return items


def _scrape_hastac(target: dict, seen: set) -> list[dict]:
    """Scrape HASTAC news listing page."""
    items = []
    resp = requests.get(target["url"], headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # HASTAC news items are typically in <h3> or <h2> inside .views-row or article containers
    candidates = soup.select(".views-row, article, .node--type-blog")
    if not candidates:
        candidates = soup.select("h2, h3")  # fallback

    for node in candidates[:10]:
        a_tag = node.find("a", href=True) if hasattr(node, "find") else None
        if not a_tag:
            continue
        link  = a_tag["href"]
        if not link.startswith("http"):
            link = "https://hastac.org" + link
        title = a_tag.get_text(strip=True) or "(no title)"
        uid   = item_id(link, title)
        if uid in seen:
            continue

        blurb_tag = node.find("p") if hasattr(node, "find") else None
        summary = textwrap.shorten(blurb_tag.get_text(" ", strip=True), 200, placeholder="…") if blurb_tag else ""

        items.append({
            "uid":      uid,
            "title":    title,
            "link":     link,
            "source":   target["name"],
            "category": target["category"],
            "date":     "",
            "summary":  summary,
        })
    return items


SCRAPER_MAP = {
    "Stanford Digital Humanities": _scrape_stanford,
    "HASTAC":                      _scrape_hastac,
}


def fetch_scraped_items(target: dict, seen: set) -> list[dict]:
    name = target["name"]
    scraper = SCRAPER_MAP.get(name)
    if not scraper:
        log.warning("No scraper registered for %s — skipping", name)
        return []
    try:
        items = scraper(target, seen)
        log.info("%-35s  %d new item(s)", name, len(items))
        return items
    except Exception as exc:
        log.error("%-35s  FAILED: %s", name, exc)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# HTML email builder
# ─────────────────────────────────────────────────────────────────────────────

# Desired category display order
CATEGORY_ORDER = [
    "Aggregators & News",
    "Tutorials & Methods",
    "Professional Orgs",
    "Institutional Blogs",
    "Scholar Blogs",
]


def _group_by_category(items: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["category"], []).append(item)
    # Sort within each group by source name for consistency
    for cat in groups:
        groups[cat].sort(key=lambda x: x["source"])
    return groups


def build_html(items: list[dict], date_range: str) -> str:
    groups = _group_by_category(items)

    # Build category sections in preferred order, then any remainder alphabetically
    ordered_cats = [c for c in CATEGORY_ORDER if c in groups]
    ordered_cats += sorted(c for c in groups if c not in CATEGORY_ORDER)

    sections_html = ""
    for cat in ordered_cats:
        cat_items = groups[cat]
        rows = ""
        for it in cat_items:
            date_span = f'<span style="color:#888;font-size:0.85em;">{it["date"]}</span>' if it["date"] else ""
            source_span = f'<span style="color:#555;font-size:0.85em;"> — {it["source"]}</span>'
            summary_p = (
                f'<p style="margin:4px 0 0 0;color:#444;font-size:0.9em;">{it["summary"]}</p>'
                if it["summary"] else ""
            )
            rows += f"""
            <div style="margin-bottom:18px;">
              <div style="margin-bottom:2px;">
                <a href="{it['link']}" style="font-weight:600;color:#1a0dab;text-decoration:none;">{it['title']}</a>
                {source_span}
                {'&nbsp;&nbsp;' + date_span if date_span else ''}
              </div>
              {summary_p}
            </div>"""

        sections_html += f"""
        <div style="margin-bottom:32px;">
          <h2 style="font-size:1.1em;font-weight:700;color:#fff;background:#3a5a8a;
                     padding:6px 12px;border-radius:4px;margin:0 0 14px 0;">
            {cat}
          </h2>
          {rows}
        </div>"""

    total = len(items)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Georgia,serif;">
  <div style="max-width:680px;margin:24px auto;background:#fff;border-radius:6px;
              box-shadow:0 2px 8px rgba(0,0,0,.12);overflow:hidden;">

    <!-- Header -->
    <div style="background:#1e3a5f;padding:24px 32px;">
      <h1 style="margin:0;color:#fff;font-size:1.5em;letter-spacing:0.02em;">
        DH Digest
      </h1>
      <p style="margin:6px 0 0 0;color:#aac4e8;font-size:0.9em;">{date_range}</p>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px;">
      <p style="margin:0 0 24px 0;color:#555;font-size:0.9em;">
        {total} new item{'s' if total != 1 else ''} across {len(groups)} category{'s' if len(groups) != 1 else ''}.
      </p>
      {sections_html}
    </div>

    <!-- Footer -->
    <div style="background:#f0f0f0;padding:14px 32px;font-size:0.78em;color:#888;
                border-top:1px solid #ddd;">
      Generated by dh-digest &nbsp;·&nbsp;
      <a href="https://github.com/your-username/dh-digest" style="color:#888;">github</a>
    </div>

  </div>
</body>
</html>"""
    return html


def build_plaintext(items: list[dict], date_range: str) -> str:
    groups = _group_by_category(items)
    ordered_cats = [c for c in CATEGORY_ORDER if c in groups]
    ordered_cats += sorted(c for c in groups if c not in CATEGORY_ORDER)

    lines = [f"DH Digest — {date_range}", "=" * 60, ""]
    for cat in ordered_cats:
        lines += [cat.upper(), "-" * len(cat), ""]
        for it in groups[cat]:
            lines.append(f"  {it['title']}")
            lines.append(f"  {it['source']}" + (f"  ({it['date']})" if it["date"] else ""))
            lines.append(f"  {it['link']}")
            if it["summary"]:
                lines.append(f"  {it['summary']}")
            lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Email sending
# ─────────────────────────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str, plain_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL

    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    log.info("Connecting to Gmail SMTP…")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    log.info("Email sent to %s", RECIPIENT_EMAIL)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    now     = datetime.now(timezone.utc)
    cutoff  = now - timedelta(days=LOOKBACK_DAYS)
    seen    = load_seen()

    log.info("Fetching RSS feeds…")
    all_items: list[dict] = []

    for feed in RSS_FEEDS:
        all_items.extend(fetch_rss_items(feed, seen, cutoff))

    log.info("Scraping non-RSS targets…")
    for target in SCRAPE_TARGETS:
        all_items.extend(fetch_scraped_items(target, seen))

    if not all_items:
        log.info("No new items found this week — nothing to send.")
        return

    log.info("Total new items: %d", len(all_items))

    date_range = f"{_fmt_date(cutoff, '%b %-d')}–{_fmt_date(now, '%-d, %Y')}"
    subject    = f"DH Digest — {date_range}"
    html_body  = build_html(all_items, date_range)
    plain_body = build_plaintext(all_items, date_range)

    send_email(subject, html_body, plain_body)

    # Only update seen_items after a successful send
    new_uids = {it["uid"] for it in all_items}
    save_seen(seen | new_uids)
    log.info("seen_items.json updated (%d total IDs).", len(seen | new_uids))


if __name__ == "__main__":
    main()
