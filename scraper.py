"""
Nepal IPO Auto-Scraper v2 — uses headless Chrome to handle JavaScript
Scrapes sharesansar.com/upcoming-issue and merolagani.com fallback
Runs every 6 hours via GitHub Actions
"""

import json
import re
import sys
import time
from datetime import datetime
from urllib.request import Request, urlopen

OUTPUT_FILE = "ipo_list.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def slugify(text):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return s[:60]


def parse_date(date_str):
    if not date_str:
        return ""
    date_str = date_str.strip().split(" ")[0] if " " in date_str else date_str.strip()
    formats = [
        "%Y-%m-%d", "%Y/%m/%d",
        "%b %d, %Y", "%B %d, %Y",
        "%d/%m/%Y", "%d-%m-%Y",
        "%d %b %Y", "%d %B %Y",
        "%d-%b-%Y", "%d-%B-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str


def strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# -----------------------------------------------------
# Method 1: Try Selenium (headless Chrome) for ShareSansar
# -----------------------------------------------------
def scrape_with_selenium():
    print("Trying Selenium with headless Chrome...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        print("Selenium not installed - skipping")
        return None

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={HEADERS['User-Agent']}")

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(45)

        url = "https://www.sharesansar.com/upcoming-issue"
        print(f"Loading {url}...")
        driver.get(url)

        # Wait up to 15s for any table to appear
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
            )
        except Exception:
            print("Tables didn't load in time — continuing with whatever we got")

        time.sleep(3)  # extra time for all sections to render

        html = driver.page_source
        print(f"  Got page HTML: {len(html)} chars")
        return parse_sharesansar_html(html)

    except Exception as e:
        print(f"Selenium error: {e}")
        return None
    finally:
        if driver:
            driver.quit()


def parse_sharesansar_html(html):
    """ShareSansar uses table structure with <h3 id="ipo">, <h3 id="rightshare"> etc as section headers."""
    ipos = []

    # Find each section anchor and the table that follows
    # Pattern: <h3 id="ipo">IPO</h3> ... <table>...</table>
    sections = [
        ("ipo", "IPO"),
        ("ipolocal", "IPO"),
        ("ipomigrant", "IPO"),
        ("ipoqiis", "IPO"),
        ("rightshare", "RIGHT"),
        ("fpo", "FPO"),
        ("mutualfund", "MUTUAL_FUND"),
        ("bondsAndDeb", "DEBENTURE"),
    ]

    for anchor, ipo_type in sections:
        # Find the section's content block
        pattern = rf'id\s*=\s*["\']?{re.escape(anchor)}["\']?[^>]*>(.*?)(?=id\s*=\s*["\'](?:ipo|ipolocal|ipomigrant|ipoqiis|rightshare|fpo|mutualfund|bondsAndDeb)["\']|<footer|$)'
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if not m:
            continue

        block = m.group(1)
        table_m = re.search(r"<table[^>]*>(.*?)</table>", block, re.DOTALL | re.IGNORECASE)
        if not table_m:
            continue

        table_html = table_m.group(1)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)

        if len(rows) < 2:
            continue

        # Extract header
        header_cells = re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.DOTALL | re.IGNORECASE)
        if not header_cells:
            header_cells = re.findall(r"<td[^>]*>(.*?)</td>", rows[0], re.DOTALL | re.IGNORECASE)
        headers_lower = [strip_tags(h).lower() for h in header_cells]

        # Find columns
        def find_col(*keywords):
            for i, h in enumerate(headers_lower):
                for kw in keywords:
                    if kw in h:
                        return i
            return -1

        col_company = find_col("company", "name", "issue")
        col_open = find_col("open", "issue date")
        col_close = find_col("close", "end")
        col_units = find_col("unit", "kitta", "qty", "quantity")
        col_price = find_col("price", "rate")

        if col_company < 0:
            print(f"  Section {anchor}: no company column found in {headers_lower}")
            continue

        section_count = 0
        for row in rows[1:]:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
            cells = [strip_tags(c) for c in cells]
            if not cells or len(cells) <= col_company:
                continue
            name = cells[col_company].strip()
            if not name or len(name) < 3 or name.lower() in ("company name", "name"):
                continue

            open_date = parse_date(cells[col_open]) if 0 <= col_open < len(cells) else ""
            close_date = parse_date(cells[col_close]) if 0 <= col_close < len(cells) else ""

            kitta = 10
            if 0 <= col_units < len(cells):
                digits = re.sub(r"[^\d]", "", cells[col_units])
                if digits:
                    try:
                        v = int(digits)
                        if v < 1000:
                            kitta = v
                    except ValueError:
                        pass

            price = 100
            if 0 <= col_price < len(cells):
                digits = re.sub(r"[^\d]", "", cells[col_price])
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
            section_count += 1

        print(f"  Section {anchor} ({ipo_type}): {section_count} entries")

    return ipos


# -----------------------------------------------------
# Method 2: Try MeroLagani as fallback
# -----------------------------------------------------
def scrape_merolagani():
    print("Trying merolagani.com as fallback...")
    try:
        url = "https://merolagani.com/Ipo.aspx"
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # MeroLagani returns server-rendered HTML
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
        ipos = []
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
            cells = [strip_tags(c) for c in cells]
            if len(cells) < 4:
                continue
            name = cells[0]
            if not name or len(name) < 5 or "company" in name.lower():
                continue

            # Try to find date-like patterns in any cell
            dates = []
            for c in cells:
                if re.search(r"\d{4}-\d{2}-\d{2}", c):
                    dates.append(re.search(r"\d{4}-\d{2}-\d{2}", c).group())
            open_date = dates[0] if len(dates) >= 1 else ""
            close_date = dates[1] if len(dates) >= 2 else ""

            ipos.append({
                "id": f"ipo_{slugify(name)}",
                "name": name,
                "openDate": open_date,
                "closeDate": close_date,
                "kitta": 10,
                "price": 100,
                "type": "IPO",
                "sector": "",
            })
        print(f"  MeroLagani: {len(ipos)} entries")
        return ipos
    except Exception as e:
        print(f"MeroLagani error: {e}")
        return []


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
        "source": "sharesansar.com (auto-scraped via Selenium)",
        "ipos": list(by_id.values()),
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(final['ipos'])} total IPOs ({added} new)")
    return added


if __name__ == "__main__":
    all_ipos = []

    # Try Selenium first
    s_ipos = scrape_with_selenium()
    if s_ipos:
        all_ipos.extend(s_ipos)

    # Try MeroLagani as supplement
    m_ipos = scrape_merolagani()
    if m_ipos:
        all_ipos.extend(m_ipos)

    if not all_ipos:
        print("No IPOs found from any source — keeping existing data")
        sys.exit(0)

    added = merge_and_save(all_ipos)
    print(f"Done! Added {added} new IPO(s)")
