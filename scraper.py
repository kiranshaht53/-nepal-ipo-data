"""
Nepal IPO Auto-Scraper
Scrapes sharesansar.com/upcoming-issue and updates ipo_list.json
Runs automatically every 6 hours via GitHub Actions
"""

import json
import re
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

URL = "https://www.sharesansar.com/upcoming-issue"
OUTPUT_FILE = "ipo_list.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url):
    """Download the upcoming issues page."""
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except (URLError, HTTPError) as e:
        print(f"Fetch error: {e}")
        return None


def slugify(text):
    """Make a safe ID from a company name."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return s[:60]


def parse_date(date_str):
    """Try to parse various date formats Sharesansar uses."""
    date_str = date_str.strip()
    formats = [
        "%Y-%m-%d", "%Y/%m/%d",
        "%b %d, %Y", "%B %d, %Y",
        "%d/%m/%Y", "%d-%m-%Y",
        "%d %b %Y", "%d %B %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str  # return as-is if no format matches


def extract_tables(html):
    """Extract all <table> blocks."""
    return re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL | re.IGNORECASE)


def strip_tags(s):
    """Remove HTML tags and decode entities."""
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_rows(table_html):
    """Extract all <tr> rows with their <td> cells."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)
    parsed = []
    for r in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.DOTALL | re.IGNORECASE)
        cells = [strip_tags(c) for c in cells]
        if cells:
            parsed.append(cells)
    return parsed


def find_col(headers, *keywords):
    """Find first column whose header matches any keyword."""
    for i, h in enumerate(headers):
        h_lower = h.lower()
        for kw in keywords:
            if kw in h_lower:
                return i
    return -1


def parse_table(table_html, ipo_type="IPO"):
    """Parse one table — auto-detect columns."""
    rows = parse_rows(table_html)
    if len(rows) < 2:
        return []

    headers = [h.lower() for h in rows[0]]

    col_company = find_col(headers, "company", "name", "issue")
    col_open    = find_col(headers, "open")
    col_close   = find_col(headers, "close")
    col_units   = find_col(headers, "unit", "kitta", "qty", "quantity")
    col_price   = find_col(headers, "price", "rate")

    if col_company < 0 or col_open < 0:
        return []

    ipos = []
    for row in rows[1:]:
        if len(row) <= col_company:
            continue
        name = row[col_company].strip()
        if not name or len(name) < 3:
            continue

        open_date  = parse_date(row[col_open]) if col_open >= 0 and col_open < len(row) else ""
        close_date = parse_date(row[col_close]) if col_close >= 0 and col_close < len(row) else ""

        # Parse units (kitta)
        kitta = 10
        if col_units >= 0 and col_units < len(row):
            digits = re.sub(r"[^\d]", "", row[col_units])
            if digits:
                try:
                    val = int(digits)
                    # If it's the total units, we keep 10 as default per-applicant
                    # If it's "min units per applicant", use it
                    if val < 1000:
                        kitta = val
                except ValueError:
                    pass

        # Parse price
        price = 100
        if col_price >= 0 and col_price < len(row):
            digits = re.sub(r"[^\d]", "", row[col_price])
            if digits:
                try:
                    price = int(digits)
                except ValueError:
                    pass

        ipos.append({
            "id": f"{ipo_type.lower()}_{slugify(name)}",
            "name": name,
            "openDate": open_date,
            "closeDate": close_date,
            "kitta": kitta,
            "price": price,
            "type": ipo_type,
            "sector": "",
        })
    return ipos


def detect_table_type(html_before_table):
    """Look at heading text before the table to guess IPO/FPO/Right."""
    text = strip_tags(html_before_table[-1000:]).lower()
    if "right" in text:
        return "RIGHT"
    if "fpo" in text or "further" in text:
        return "FPO"
    if "debenture" in text:
        return "DEBENTURE"
    if "mutual" in text:
        return "MUTUAL_FUND"
    return "IPO"


def scrape():
    print(f"Fetching {URL}...")
    html = fetch_html(URL)
    if not html:
        print("Could not fetch page — keeping existing data")
        return None

    # Find each table position so we can detect its type from preceding heading
    table_iter = re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL | re.IGNORECASE)
    all_ipos = []

    for match in table_iter:
        table_html = match.group(1)
        before = html[:match.start()]
        ipo_type = detect_table_type(before)
        ipos = parse_table(table_html, ipo_type)
        all_ipos.extend(ipos)
        print(f"  Found {len(ipos)} {ipo_type} entries")

    return all_ipos


def merge_and_save(new_ipos):
    """Merge with existing ipo_list.json — preserve manual additions."""
    existing = []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get("ipos", [])
    except FileNotFoundError:
        pass

    # Index existing by id
    by_id = {ipo["id"]: ipo for ipo in existing}

    # Add new ones (don't overwrite existing — let manual edits win)
    added = 0
    for ipo in new_ipos:
        if ipo["id"] not in by_id:
            by_id[ipo["id"]] = ipo
            added += 1

    final = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "sharesansar.com/upcoming-issue (auto-scraped)",
        "ipos": list(by_id.values()),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(final['ipos'])} total IPOs ({added} new)")
    return added


if __name__ == "__main__":
    new_ipos = scrape()
    if new_ipos is None:
        print("Scrape failed — exiting without changes")
        sys.exit(0)  # don't fail the workflow
    if not new_ipos:
        print("No IPOs found on the page (it may be empty right now)")
        sys.exit(0)
    added = merge_and_save(new_ipos)
    print(f"Done! Added {added} new IPO(s)")
