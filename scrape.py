#!/usr/bin/env python3
"""
Phase 1: Scrape bulletin PDFs from parish websites.
Downloads new bulletins since last_collected and updates store.json.

Usage:
    python scrape.py
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STORE_PATH = Path("store.json")
BULLETINS_DIR = Path("bulletins")

# How far back to look on first run (no last_collected in store)
DEFAULT_LOOKBACK_WEEKS = 8

SOURCES = {
    "epi": {
        "type": "parishesonline",
        # Base URL stays constant; bulletins are at {base}{YYYYMMDD}B.pdf
        "base_url": "https://container.parishesonline.com/bulletins/01/0382/",
    },
    "hspht": {
        "type": "discovermass",
        "url": "https://discovermass.com/church/st-patrick-bloomington-il/",
    },
    "spm": {
        "type": "discovermass",
        "url": "https://discovermass.com/church/st-patrick-church-of-merna-bloomington-il/",
    },
    "smb": {
        "type": "discovermass",
        "url": "https://discovermass.com/church/st-mary-bloomington-il/",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def load_store() -> dict:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    return {
        "sources": {},
        "next_id": 1,
        "events": [],
        "bulletins": [],
    }


def save_store(store: dict) -> None:
    STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def get_last_collected(store: dict, source_id: str) -> date:
    date_str = store["sources"].get(source_id, {}).get("last_collected")
    if date_str:
        return date.fromisoformat(date_str)
    return date.today() - timedelta(weeks=DEFAULT_LOOKBACK_WEEKS)


def set_last_collected(store: dict, source_id: str, d: date) -> None:
    if source_id not in store["sources"]:
        store["sources"][source_id] = {}
    existing = store["sources"][source_id].get("last_collected")
    if not existing or d.isoformat() > existing:
        store["sources"][source_id]["last_collected"] = d.isoformat()


def record_bulletin(store: dict, source_id: str, bulletin_date: date, url: str, local_path: Path) -> None:
    for b in store["bulletins"]:
        if b["source"] == source_id and b["date"] == bulletin_date.isoformat():
            return  # already recorded
    store["bulletins"].append({
        "source": source_id,
        "date": bulletin_date.isoformat(),
        "url": url,
        "local_path": str(local_path),
        "processed": False,
    })


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_pdf(url: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    r.raise_for_status()
    content = r.content
    if not content.startswith(b"%PDF"):
        raise ValueError(f"Response does not look like a PDF (Content-Type: {r.headers.get('Content-Type')})")
    dest_path.write_bytes(content)


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

def scrape_parishesonline(source_id: str, config: dict, store: dict) -> list[date]:
    """
    Probe for bulletins on each Sunday from last_collected to today.
    URL pattern: {base_url}{YYYYMMDD}B.pdf
    Returns list of newly downloaded bulletin dates.
    """
    base_url = config["base_url"]
    last_collected = get_last_collected(store, source_id)
    today = date.today()

    # Advance to the first Sunday strictly after last_collected
    candidate = last_collected + timedelta(days=1)
    while candidate.weekday() != 6:  # 6 = Sunday
        candidate += timedelta(days=1)

    downloaded = []
    while candidate <= today:
        local_path = BULLETINS_DIR / source_id / f"{candidate.isoformat()}.pdf"

        url = f"{base_url}{candidate.strftime('%Y%m%d')}B.pdf"

        if local_path.exists():
            print(f"  {candidate} already on disk, skipping")
            record_bulletin(store, source_id, candidate, url, local_path)
            set_last_collected(store, source_id, candidate)
            candidate += timedelta(weeks=1)
            continue
        print(f"  Trying {candidate}: {url}")
        try:
            r = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                download_pdf(url, local_path)
                record_bulletin(store, source_id, candidate, url, local_path)
                set_last_collected(store, source_id, candidate)
                downloaded.append(candidate)
                print(f"  Downloaded {candidate}")
            else:
                print(f"  {candidate}: HTTP {r.status_code}, no bulletin found")
        except Exception as e:
            print(f"  {candidate}: Error — {e}")

        candidate += timedelta(weeks=1)

    return downloaded


def scrape_discovermass(source_id: str, config: dict, store: dict) -> list[date]:
    """
    Fetch the parish page, parse current and archive bulletin links,
    filter to dates after last_collected, download new ones.
    Returns list of newly downloaded bulletin dates.
    """
    last_collected = get_last_collected(store, source_id)
    today = date.today()

    print(f"  Fetching {config['url']}")
    r = requests.get(config["url"], headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Gather all bulletin <a> tags: current first, then archive
    links = []
    current_span = soup.find("span", class_="bulletin-current")
    if current_span:
        a = current_span.find("a")
        if a:
            links.append(a)

    archive_span = soup.find("span", class_="bulletin-archive")
    if archive_span:
        links.extend(archive_span.find_all("a"))

    downloaded = []
    for a in links:
        text = a.get_text(strip=True)
        href = a.get("href", "").strip()
        if not href or not text:
            continue

        try:
            bulletin_date = datetime.strptime(text, "%b %d, %Y").date()
        except ValueError:
            print(f"  Could not parse date from link text: {text!r}")
            continue

        if bulletin_date <= last_collected or bulletin_date > today:
            continue

        local_path = BULLETINS_DIR / source_id / f"{bulletin_date.isoformat()}.pdf"
        if local_path.exists():
            print(f"  {bulletin_date} already on disk, skipping")
            record_bulletin(store, source_id, bulletin_date, href, local_path)
            set_last_collected(store, source_id, bulletin_date)
            continue

        print(f"  Downloading {bulletin_date}: {href}")
        try:
            download_pdf(href, local_path)
            record_bulletin(store, source_id, bulletin_date, href, local_path)
            set_last_collected(store, source_id, bulletin_date)
            downloaded.append(bulletin_date)
            print(f"  Downloaded {bulletin_date}")
        except Exception as e:
            print(f"  {bulletin_date}: Error — {e}")

    return downloaded


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    store = load_store()
    BULLETINS_DIR.mkdir(exist_ok=True)

    total = 0
    for source_id, config in SOURCES.items():
        print(f"\n[{source_id}]")
        source_type = config["type"]
        if source_type == "parishesonline":
            downloaded = scrape_parishesonline(source_id, config, store)
        elif source_type == "discovermass":
            downloaded = scrape_discovermass(source_id, config, store)
        else:
            print(f"  Unknown source type: {source_type!r}")
            continue

        total += len(downloaded)
        save_store(store)  # Save after each source so partial runs aren't lost

    print(f"\nDone. {total} new bulletin(s) downloaded.")


if __name__ == "__main__":
    main()
