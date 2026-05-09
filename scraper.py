"""
Nepal IPO News Scraper v6 — DEBUG VERSION
Shows exactly what's found so we can diagnose and fix.
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
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#039;", "'").replace("&quot;", '"')
    s = re.sub(r"\s+", " ", s).strip()
    return s


SKIP_IF_FOUND = [
    " agm ", "appoints", "oversubscribed",
    "concludes ipo allotment", "issue manager",
    "approved", "pipeline", "approves",
    "icra ", "credit rating",
    "ipo result", "allotment",
    "extended", "refund", "premium price",
    "calls agm", "merger", "acquisition",
    "files ipo", "submits ipo",
]

# RELAXED active patterns - more general
ACTIVE_REQUIRED = [
    r"ipo for general public",
    r"ipo shares from",
    r"ipo (?:opens?|opening|begins|starts|launches)",
    r"closing (?:today|tomorrow)",
    r"shares from today",
    r"opens for subscription",
    r"fpo for general public",
    r"fpo (?:opens?|begins)",
    r"right shares? (?:for general|opens|begins)",
    r"public offering",
    r"\bipo\b.*\b(?:today|now|opens|begins)",
]


def looks_like_active_ipo(headline):
    h = " " + headline.lower() + " "
    for skip in SKIP_IF_FOUND:
        if skip in h:
            return False
    for pat in ACTIVE_REQUIRED:
        if re.search(pat, h):
            return True
    return False


def extract_company_name(headline):
    text = re.sub(r"^ipo for general public:?\s*", "", headline, flags=re.IGNORECASE)
    text = re.sub(r"^ipo for (?:foreign nepalese (?:immigrants|migrant)|qiis):?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^fpo for general public:?\s*", "", text, flags=re.IGNORECASE)

    cuts = [
        r"\s+(?:to issue|issuing|closing|opens?|opening|launches|begins|starts|concludes|today|tomorrow|from)\s",
        r"\s+issue \d",
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


def find_news_items(html):
    """Find all news items robustly."""
    items = []
    seen_urls = set()

    a_pattern = r'<a\s+([^>]*href\s*=\s*["\']?(/newsdetail/[^"\'>\s]+)["\']?[^>]*)>(.*?)</a>'
    for full_attrs, url, inner in re.findall(a_pattern, html, re.DOTALL | re.IGNORECASE):
        if url in seen_urls:
            continue

        title_match = re.search(r'title\s*=\s*["\']([^"\']+)["\']', full_attrs, re.IGNORECASE)
        if title_match:
            title = title_match.group(1)
        else:
            inner_clean = strip_tags(inner)
            if inner_clean and len(inner_clean) > 10:
                title = inner_clean
            else:
                continue

        if not title or len(title) < 10:
            continue

        seen_urls.add(url)
        items.append((url, title.strip()))

    return items


def parse_news_page(html):
    if not html:
        return []

    items = find_news_items(html)
    print(f"\nFound {len(items)} news items on page\n")

    if not items:
        # Show what /newsdetail/ links exist
        sample = re.findall(r'/newsdetail/[a-zA-Z0-9-]+', html)[:10]
        print(f"Debug: {len(sample)} /newsdetail/ patterns in raw HTML")
        for s in sample[:5]:
            print(f"  {s}")
        return []

    # *** DEBUG: Show ALL items first so we can see what's there ***
    print("=== ALL NEWS ITEMS FOUND ===")
    for i, (url, title) in enumerate(items, 1):
        print(f"{i}. {title[:100]}")
        print(f"   URL: {url[:80]}")
    print("=== END DEBUG ===\n")

    today = datetime.now()
    thirty_days_ago = today - timedelta(days=30)

    ipos = []
    for url, title in items:
        url_date = extract_date_from_url(url)
        if not url_date:
            print(f"  SKIP (no date): {title[:60]}")
            continue

        try:
            d = datetime.strptime(url_date, "%Y-%m-%d")
            if d < thirty_days_ago:
                print(f"  SKIP (too old, {url_date}): {title[:60]}")
                continue
        except ValueError:
            continue

        if not looks_like_active_ipo(title):
            print(f"  SKIP (not active IPO): {title[:80]}")
            continue

        company = extract_company_name(title)
        if not company or len(company) < 5:
            print(f"  SKIP (no company name): {title[:60]}")
            continue

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
            old = by_id[ipo["id"]]
            if not old.get("openDate") and ipo.get("openDate"):
                by_id[ipo["id"]] = ipo
                updated += 1

    final = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "sharesansar.com/category/ipo-fpo-news (auto-scraped)",
        "ipos": list(by_id.values()),
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(final['ipos'])} total IPOs ({added} new, {updated} updated)")
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
        print("\nNo active IPOs found this run")
        sys.exit(0)

    print(f"\n=== {len(ipos)} ACTIVE IPO(s) detected ===")
    for ipo in ipos:
        print(f"  • {ipo['name']} ({ipo['type']}) — opened {ipo['openDate']}")

    added = merge_and_save(ipos)
    print(f"\nDone! Added {added} new IPO(s)")
