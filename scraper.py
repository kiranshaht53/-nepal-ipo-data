"""
Nepal IPO News Scraper v5
Robust regex - handles ShareSansar's actual HTML structure.
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
    for skip in SKIP_IF_FOUND:
        if skip in h:
            return False
    for pat in ACTIVE_REQUIRED:
        if re.search(pat, h):
            return True
    return False


def strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#039;", "'").replace("&quot;", '"')
    s = re.sub(r"\s+", " ", s).strip()
    return s


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


def find_news_items(html):
    """Find all news items - tries multiple regex patterns to be robust."""
    items = []
    seen_urls = set()

    # Pattern 1: Find all <a> tags with /newsdetail/ href
    # This catches both <a href="..." title="..."> AND <a title="..." href="...">
    # Then we look at the text inside the <a> tag if title attr is missing
    a_pattern = r'<a\s+([^>]*href\s*=\s*["\']?(/newsdetail/[^"\'>\s]+)["\']?[^>]*)>(.*?)</a>'
    for full_attrs, url, inner in re.findall(a_pattern, html, re.DOTALL | re.IGNORECASE):
        if url in seen_urls:
            continue

        # Try to get title from title="..." attribute
        title_match = re.search(r'title\s*=\s*["\']([^"\']+)["\']', full_attrs, re.IGNORECASE)
        if title_match:
            title = title_match.group(1)
        else:
            # Use the link's inner text
            title = strip_tags(inner)

        if not title or len(title) < 10:
            continue

        # Skip image-only links (the photo links)
        if title.startswith("http") or "<img" in inner.lower() and not title_match:
            continue

        seen_urls.add(url)
        items.append((url, title.strip()))

    return items


def parse_news_page(html):
    if not html:
        return []

    items = find_news_items(html)
    print(f"Found {len(items)} news items on page")

    if not items:
        # Debug: show first 500 chars to help diagnose
        # Look for any /newsdetail/ link at all
        sample = re.findall(r'href\s*=\s*["\']?(/newsdetail/[^"\'>\s]+)', html)
        print(f"Debug: found {len(sample)} /newsdetail/ links in raw HTML")
        if sample:
            print(f"  First link: {sample[0][:80]}")
        return []

    today = datetime.now()
    thirty_days_ago = today - timedelta(days=30)

    ipos = []
    for url, title in items:
        url_date = extract_date_from_url(url)
        if not url_date:
            continue

        try:
            d = datetime.strptime(url_date, "%Y-%m-%d")
            if d < thirty_days_ago:
                continue
        except ValueError:
            continue

        if not looks_like_active_ipo(title):
            print(f"  SKIP (not active): {title[:80]}")
            continue

        company = extract_company_name(title)
        if not company or len(company) < 5:
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
