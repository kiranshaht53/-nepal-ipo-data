"""
Nepal IPO News Scraper v3
Scrapes sharesansar.com/category/ipo-fpo-news (server-rendered, no JS needed)
Extracts active IPOs from news headlines using smart pattern matching.
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


def strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Skip these headlines — they aren't actual active IPOs
SKIP_PATTERNS = [
    r"\bagm\b",
    r"\bappoints\b",
    r"\boversubscribed\b",
    r"\bconcludes ipo allotment\b",
    r"\bissue manager\b",
    r"\bproposal\b.*\bapproved\b",
    r"\bpipeline\b",
    r"\bsebon\b.*\bapproves?\b",
    r"\bicra\b",
    r"\bcredit rating\b",
    r"\bipo result\b",
    r"\ballotment\b",
    r"\bextended\b",
    r"\brefund\b",
    r"\bclosing today\b.*\boversubscribed\b",
]

# Match headlines that announce an active/opening IPO
ACTIVE_PATTERNS = [
    r"ipo for general public",
    r"issue \d+[,\d]* units? ipo shares from",
    r"to issue \d+[,\d]* units? ipo shares from",
    r"ipo (?:issue|opens?|opening|begins|starts|launches)",
    r"ipo for (?:foreign nepalese|migrant|qiis)",
    r"closing (?:today|tomorrow)\b(?!.*oversubscribed)",
    r"fpo (?:issue|opens?|begins|starts)",
    r"right shares? (?:issue|opens?|begins)",
    r"public offering",
]


def looks_like_active_ipo(headline):
    """Decide if this headline is about an active/opening IPO."""
    h = headline.lower()
    # Skip known non-actionable types
    for sp in SKIP_PATTERNS:
        if re.search(sp, h):
            return False
    # Match active patterns
    for ap in ACTIVE_PATTERNS:
        if re.search(ap, h):
            return True
    return False


def extract_company_name(headline):
    """Pull the company name out of a headline."""
    # Remove "IPO for General Public:" prefix etc.
    text = re.sub(r"^ipo for general public:?\s*", "", headline, flags=re.IGNORECASE)
    text = re.sub(r"^ipo for (?:foreign nepalese (?:immigrants|migrant)|qiis):?\s*", "", text, flags=re.IGNORECASE)

    # Take everything before keywords like "Issue", "to Issue", "Closing", "Opens", etc.
    cuts = [
        r"\s+(?:to issue|issue|issuing|closing|opens?|opening|launches|begins|starts|concludes|today|tomorrow|from)\s",
    ]
    for cut in cuts:
        m = re.search(cut, text, re.IGNORECASE)
        if m:
            text = text[:m.start()]
            break

    # Clean up trailing punctuation
    text = re.sub(r"[,;:]\s*$", "", text).strip()
    return text


def extract_units(headline):
    """Extract total kitta/units mentioned in headline (e.g., '25,15,455 units')."""
    m = re.search(r"(\d[\d,]*)\s*units?", headline, re.IGNORECASE)
    if not m:
        return None
    digits = m.group(1).replace(",", "")
    try:
        return int(digits)
    except ValueError:
        return None


def extract_date_from_url(url):
    """SharSansar news URLs end with -YYYY-MM-DD."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})$", url.strip("/"))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def parse_news_page(html):
    """Find news article links and extract IPO info."""
    if not html:
        return []

    # Each news card has structure:
    # <a href="/newsdetail/...">...img...</a>
    # <h4><a href="/newsdetail/..." title="...">Title</a></h4>
    # ... date text ...

    # Find all newsdetail links with their titles
    pattern = r'<a[^>]+href="(/newsdetail/[^"]+)"[^>]*title="([^"]+)"'
    matches = re.findall(pattern, html, re.IGNORECASE)

    # De-duplicate by URL
    seen = set()
    items = []
    for url, title in matches:
        if url in seen:
            continue
        seen.add(url)
        items.append((url, title))

    print(f"Found {len(items)} news items on page")

    today = datetime.now()
    ninety_days_ago = today - timedelta(days=90)

    ipos = []
    for url, title in items:
        # Only consider news from last 90 days
        url_date = extract_date_from_url(url)
        if url_date:
            try:
                d = datetime.strptime(url_date, "%Y-%m-%d")
                if d < ninety_days_ago:
                    continue
            except ValueError:
                pass

        # Filter: only active IPOs
        if not looks_like_active_ipo(title):
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

        # Extract date — use URL date as opening date heuristic
        open_date = url_date
        # Try to estimate close date as +5 days
        close_date = ""
        if open_date:
            try:
                d = datetime.strptime(open_date, "%Y-%m-%d")
                close_date = (d + timedelta(days=4)).strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Extract total units from title
        total_units = extract_units(title)

        # For most retail IPOs, applicants apply for 10 kitta minimum
        kitta = 10

        ipos.append({
            "id": f"{ipo_type.lower()}_{slugify(company)}",
            "name": company,
            "openDate": open_date,
            "closeDate": close_date,
            "kitta": kitta,
            "price": 100,  # default — most IPOs in Nepal at par 100
            "type": ipo_type,
            "sector": "",
            "source_url": "https://www.sharesansar.com" + url,
            "headline": title,
        })

    return ipos


def merge_and_save(new_ipos):
    existing = []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get("ipos", [])
    except FileNotFoundError:
        pass

    by_id = {ipo["id"]: ipo for ipo in existing}
    added = 0
    for ipo in new_ipos:
        if ipo["id"] not in by_id:
            by_id[ipo["id"]] = ipo
            added += 1

    final = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "sharesansar.com/category/ipo-fpo-news (auto-scraped)",
        "ipos": list(by_id.values()),
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(final['ipos'])} total IPOs ({added} new)")
    return added


if __name__ == "__main__":
    print(f"Fetching {NEWS_URL}...")
    html = fetch_html(NEWS_URL)

    if not html:
        print("Could not fetch — keeping existing data")
        sys.exit(0)

    print(f"Got {len(html)} chars of HTML")
    ipos = parse_news_page(html)

    if not ipos:
        print("No active IPOs found in news (may be a quiet week)")
        sys.exit(0)

    print(f"\nDetected {len(ipos)} active IPO(s):")
    for ipo in ipos:
        print(f"  - {ipo['name']} ({ipo['type']}) opened {ipo['openDate']}")

    added = merge_and_save(ipos)
    print(f"\nDone! Added {added} new IPO(s)")
