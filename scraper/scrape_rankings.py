from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from core.market_data import DATA_DIR, save_json

SECTOR_URL = "https://www.tradingview.com/markets/stocks-usa/sectorandindustry-sector/"
INDUSTRY_URL = "https://www.tradingview.com/markets/stocks-usa/sectorandindustry-industry/"

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUEST_TIMEOUT = 30


def normalize_label(value: str) -> str:
    return " ".join(value.split())


def parse_percent(value: str) -> float | None:
    cleaned = (
        value.strip()
        .replace("%", "")
        .replace(",", "")
        .replace("\u202f", "")
        .replace("\u00a0", "")
        .replace("\u2212", "-")
        .replace(" ", "")
    )
    if cleaned in {"", "-", "--", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def scrape_table(url: str, label_key: str) -> list[dict]:
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    table_rows = soup.select("tbody tr")

    items = []
    for row in table_rows:
        cells = row.select("td")
        if len(cells) < 4:
            continue

        label = normalize_label(cells[0].get_text(" ", strip=True))
        performance = parse_percent(cells[3].get_text(" ", strip=True))
        if not label or performance is None:
            continue

        items.append({label_key: label, "performance": performance})

    items.sort(key=lambda item: item["performance"], reverse=True)
    for index, item in enumerate(items, start=1):
        item["rank"] = index
    return items


def scrape_once() -> None:
    sectors = scrape_table(SECTOR_URL, "sector")
    industries = scrape_table(INDUSTRY_URL, "industry")
    if not sectors or not industries:
        raise RuntimeError(
            f"Scrape returned empty data (sectors={len(sectors)}, industries={len(industries)})"
        )

    save_json(DATA_DIR / "sectors.json", sectors)
    save_json(DATA_DIR / "industries.json", industries)

    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] sectors={len(sectors)} industries={len(industries)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape TradingView sector/industry rankings.")
    parser.add_argument("--interval", type=int, default=60, help="Refresh interval in seconds.")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously at --interval seconds. Without this flag, scrape once and exit.",
    )
    args = parser.parse_args()

    if not args.loop:
        scrape_once()
        return

    while True:
        try:
            scrape_once()
        except Exception as exc:  # noqa: BLE001
            timestamp = datetime.now(timezone.utc).isoformat()
            print(f"[{timestamp}] scrape failed: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
