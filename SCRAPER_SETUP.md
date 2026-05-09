# Nepal IPO Auto-Scraper Setup

## What this does
- Runs every 6 hours automatically on GitHub
- Visits sharesansar.com/upcoming-issue
- Finds new IPOs, FPOs, and Right Shares
- Updates ipo_list.json automatically
- Your phone app picks up new IPOs when you tap Sync

## Setup (one-time, 5 minutes)

### Step 1: Upload these files to your nepal-ipo-data repo
You need to upload TWO new files to your existing nepal-ipo-data repo:

1. scraper.py
2. .github/workflows/scrape.yml

### Step 2: Enable GitHub Actions write permission
1. Go to your repo on github.com
2. Click Settings tab (top of repo page)
3. In the left sidebar, click Actions -> General
4. Scroll down to "Workflow permissions"
5. Select "Read and write permissions"
6. Click Save

### Step 3: Trigger the first run manually
1. Go to your repo -> Actions tab (top of page)
2. Click "Auto-update IPO List" in the left sidebar
3. Click "Run workflow" button (right side)
4. Click the green "Run workflow" confirmation
5. Wait 30 seconds, refresh the page
6. You should see a green checkmark when it's done

After this, it will run automatically every 6 hours forever!

## How to verify it works
- Open your repo on GitHub
- Click on ipo_list.json
- Check the "last_updated" field — it should show recent date/time
- The "source" field should say: "sharesansar.com/upcoming-issue (auto-scraped)"
- You should see real Nepal IPOs in the list

## Troubleshooting
- If Actions tab shows red X: click on it to see the error
- Most common: "Workflow permissions" not set to read/write (Step 2)
- Scraper runs but finds 0 IPOs: ShareSansar may have no upcoming issues right now
- Just wait — when an IPO is announced, it will auto-appear within 6 hours

## Manual edits still work
- You can still manually edit ipo_list.json on GitHub
- The scraper preserves your manual entries (won't overwrite)
- It only ADDS new IPOs, never removes
