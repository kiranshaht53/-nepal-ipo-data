"""
Nepal IPO News Scraper v4 — STRICT VERSION
Only includes IPOs with confirmed opening dates from active news.
"""

import json
import re
import sys
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

OUTPUT_FILE = "ipo_list.json"
NEWS_URL = "https://www.sharesansar.com/category/ipo-fpo-news"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Fetch error: {e}")
        return None


def slugify(text):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return s[:60]


# ====== STRICT FILTERING ======

# Skip these — NOT active IPOs
SKIP_IF_FOUND = [
    "agm", "appoints", "oversubscribed",
    "concludes ipo allotment", "issue manager",
    "approved", "pipeline", "approves",
    "icra", "credit rating",
    "ipo result", "allotment",
    "extended", "refund", "premium price",
    "calls agm", "merger", "acquisition",
    "to issue ipo", "plans ipo",
    "files ipo", "submits ipo",
]

# REQUIRE one of these — confirms the IPO is actively issuing right now
ACTIVE_REQUIRED = [
    r"ipo for general public",
    r"issue \d+[,\d]* units? ipo shares from",
    r"to issue \d+[,\d]* units? ipo shares from",
    r"ipo opens?\b",
    r"ipo opening today",
    r"closing today",
    r"closing tomorrow",
    r"shares from today",
    r"opens for subscription",
    r"begins ipo issue",
    r"starts ipo",
    r"fpo for general public",
    r"fpo opens?\b",
    r"right shares? for general",
    r"public offering opens",
]


def looks_like_active_ipo(headline):
    h = headline.lower()
    # Skip noise first
    for skip in SKIP_IF_FOUND:
        if skip in h:
            return False
    # Must match an active pattern
    for pat in ACTIVE_REQUIRED:
        if re.search(pat, h):
            return True
    return False


def extract_company_name(headline):
    text = re.sub(r"^ipo for general public:?\s*", "", headline, flags=re.IGNORECASE)
    text = re.sub(r"^ipo for (?:foreign nepalese (?:immigrants|migrant)|qiis):?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^fpo for general public:?\s*", "", text, flags=re.IGNORECASE)

    cuts = [
        r"\s+(?:to issue|issue|issuing|closing|opens?|opening|launches|begins|starts|concludes|today|tomorrow|from)\s",
    ]
    for cut in cuts:
        m = re.search(cut, text, re.IGNORECASE)
        if m:
            text = text[:m.start()]
            break
    text = re.sub(r"[,;:]\s*$", "", text).strip()
    return text


def extract_date_from_url(url):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})$", url.strip("/"))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def parse_news_page(html):
    if not html:
        return []

    pattern = r'<a[^>]+href="(/newsdetail/[^"]+)"[^>]*title="([^"]+)"'
    matches = re.findall(pattern, html, re.IGNORECASE)

    seen = set()
    items = []
    for url, title in matches:
        if url in seen:
            continue
        seen.add(url)
        items.append((url, title))

    print(f"Found {len(items)} news items on page")

    # ONLY KEEP IPOs from the LAST 30 DAYS — older ones are stale/closed
    today = datetime.now()
    thirty_days_ago = today - timedelta(days=30)

    ipos = []
    for url, title in items:
        url_date = extract_date_from_url(url)

        # MUST have a date in the URL
        if not url_date:
            print(f"  SKIP (no date): {title[:60]}")
            continue

        # MUST be recent
        try:
            d = datetime.strptime(url_date, "%Y-%m-%d")
            if d < thirty_days_ago:
                continue  # silent skip — old news
        except ValueError:
            continue

        # MUST be an active IPO
        if not looks_like_active_ipo(title):
            print(f"  SKIP (not active): {title[:80]}")
            continue

        company = extract_company_name(title)
        if not company or len(company) < 5:
            continue

        # Determine type
        title_lower = title.lower()
        if "fpo" in title_lower:
            ipo_type = "FPO"
        elif "right" in title_lower:
            ipo_type = "RIGHT"
        elif "migrant" in title_lower or "foreign nepalese" in title_lower:
            ipo_type = "IPO_MIGRANT"
        elif "qiis" in title_lower:
            ipo_type = "IPO_QII"
        else:
            ipo_type = "IPO"

        # Estimate dates
        open_date = url_date
        close_date = ""
        try:
            d = datetime.strptime(open_date, "%Y-%m-%d")
            close_date = (d + timedelta(days=4)).strftime("%Y-%m-%d")
        except ValueError:
            pass

        ipos.append({
            "id": f"{ipo_type.lower()}_{slugify(company)}",
            "name": company,
            "openDate": open_date,
            "closeDate": close_date,
            "kitta": 10,
            "price": 100,
            "type": ipo_type,
            "sector": "",
            "source_url": "https://www.sharesansar.com" + url,
            "headline": title,
        })
        print(f"  KEEP: {company} ({ipo_type}) — {open_date}")

    return ipos


def merge_and_save(new_ipos):
    """Merge with existing — REPLACE entries with same ID to update dates."""
    existing = []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get("ipos", [])
    except FileNotFoundError:
        pass

    by_id = {ipo["id"]: ipo for ipo in existing}
    added = 0
    updated = 0
    for ipo in new_ipos:
        if ipo["id"] not in by_id:
            by_id[ipo["id"]] = ipo
            added += 1
        else:
            # Update if old entry has empty date but new one has date
            old = by_id[ipo["id"]]
            if not old.get("openDate") and ipo.get("openDate"):
                by_id[ipo["id"]] = ipo
                updated += 1

    final = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "sharesansar.com/category/ipo-fpo-news (auto-scraped, strict)",
        "ipos": list(by_id.values()),
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(final['ipos'])} total IPOs ({added} new, {updated} updated)")
    return added


if __name__ == "__main__":
    print(f"Fetching {NEWS_URL}...\n")
    html = fetch_html(NEWS_URL)

    if not html:
        print("Could not fetch — keeping existing data")
        sys.exit(0)

    print(f"Got {len(html)} chars of HTML\n")
    ipos = parse_news_page(html)

    if not ipos:
        print("\nNo active IPOs found in news (may be a quiet week)")
        sys.exit(0)

    print(f"\n=== {len(ipos)} ACTIVE IPO(s) detected ===")
    for ipo in ipos:
        print(f"  • {ipo['name']} ({ipo['type']}) — opened {ipo['openDate']}")

    added = merge_and_save(ipos)
    print(f"\nDone! Added {added} new IPO(s)")
