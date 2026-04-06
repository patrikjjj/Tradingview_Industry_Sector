from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TSI_DATA_DIR", str(ROOT_DIR / "data")))

SECTORS_PATH = DATA_DIR / "sectors.json"
INDUSTRIES_PATH = DATA_DIR / "industries.json"
TICKERS_CSV_PATH = DATA_DIR / "tickers.csv"
TICKER_CACHE_PATH = DATA_DIR / "ticker_cache.json"
CURRENT_TICKER_PATH = DATA_DIR / "current_ticker.json"

TICKER_CACHE_TTL = timedelta(days=7)
REQUEST_TIMEOUT = 8
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}

EXCHANGE_CANDIDATES = ("NASDAQ", "NYSE", "AMEX", "ARCA")
SYMBOL_PREFIXES = {
    "NASDAQ",
    "NYSE",
    "AMEX",
    "ARCA",
    "BATS",
    "CBOE",
    "OTC",
    "TVC",
    "INDEX",
    "SP",
    "DJ",
    "FOREX",
    "BINANCE",
    "CRYPTO",
}
NON_EQUITY_SYMBOLS = {"SP500", "NASDAQ100", "DJI", "US2000", "VIX", "DXY", "SPX"}
RANKING_CACHE: dict[Path, tuple[float, dict[str, dict], int]] = {}
RANKING_CACHE_LOCK = threading.Lock()
TICKER_CACHE_STATE: tuple[float, dict[str, Any]] | None = None
TICKER_CACHE_LOCK = threading.Lock()
STATIC_TICKER_MAPPING_STATE: tuple[float, dict[str, dict[str, str]]] | None = None
STATIC_TICKER_MAPPING_LOCK = threading.Lock()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def clear_stale_lock(lock_path: Path) -> bool:
    try:
        raw_pid = lock_path.read_text(encoding="utf-8").strip()
        pid = int(raw_pid)
    except (OSError, ValueError):
        pid = -1

    if process_is_running(pid):
        return False

    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


@contextmanager
def file_lock(path: Path, timeout_seconds: float = 2.0, poll_interval: float = 0.05):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    start = time.monotonic()
    lock_fd: int | None = None

    while True:
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                os.write(lock_fd, str(os.getpid()).encode("utf-8"))
            except OSError:
                os.close(lock_fd)
                lock_fd = None
                raise
            break
        except FileExistsError:
            clear_stale_lock(lock_path)
            if time.monotonic() - start >= timeout_seconds:
                raise TimeoutError(f"Timed out acquiring lock for {path.name}") from None
            time.sleep(poll_interval)

    try:
        yield
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def normalize_name(value: str) -> str:
    return " ".join(value.split()).lower()


def normalize_ticker(value: str) -> str:
    cleaned = value.upper().strip().replace(" ", "")
    exchange_match = re.match(r"^([A-Z]{2,12})[:\-]([A-Z0-9][A-Z0-9.\-]{0,14})$", cleaned)
    if exchange_match and exchange_match.group(1) in SYMBOL_PREFIXES:
        cleaned = exchange_match.group(2)
    elif ":" in cleaned:
        cleaned = cleaned.split(":")[-1]
    cleaned = re.sub(r"[^A-Z0-9.\-]", "", cleaned)
    return cleaned


def load_ranking_index(path: Path, key_name: str) -> tuple[dict[str, dict], int]:
    with RANKING_CACHE_LOCK:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return {}, 0

        cached = RANKING_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]

        rows = load_json(path, [])
        index: dict[str, dict] = {}
        if not isinstance(rows, list):
            RANKING_CACHE[path] = (mtime, index, 0)
            return index, 0

        for row in rows:
            if not isinstance(row, dict):
                continue
            label = row.get(key_name)
            if not isinstance(label, str):
                continue
            index[normalize_name(label)] = row

        total = len(index)
        RANKING_CACHE[path] = (mtime, index, total)
        return index, total


def load_static_ticker_mapping() -> dict[str, dict[str, str]]:
    global STATIC_TICKER_MAPPING_STATE

    with STATIC_TICKER_MAPPING_LOCK:
        try:
            mtime = TICKERS_CSV_PATH.stat().st_mtime
        except OSError:
            return {}

        if STATIC_TICKER_MAPPING_STATE and STATIC_TICKER_MAPPING_STATE[0] == mtime:
            return STATIC_TICKER_MAPPING_STATE[1]

        mapping: dict[str, dict[str, str]] = {}
        try:
            with TICKERS_CSV_PATH.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    ticker = normalize_ticker(row.get("ticker", ""))
                    sector = " ".join((row.get("sector") or "").split()).strip()
                    industry = " ".join((row.get("industry") or "").split()).strip()
                    if ticker and sector and industry:
                        mapping[ticker] = {"sector": sector, "industry": industry}
        except OSError:
            return {}

        STATIC_TICKER_MAPPING_STATE = (mtime, mapping)
        return mapping


def parse_iso8601(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_ticker_cache() -> dict[str, Any]:
    global TICKER_CACHE_STATE

    with TICKER_CACHE_LOCK:
        try:
            mtime = TICKER_CACHE_PATH.stat().st_mtime
        except OSError:
            return {}

        if TICKER_CACHE_STATE and TICKER_CACHE_STATE[0] == mtime:
            return TICKER_CACHE_STATE[1]

        cache = load_json(TICKER_CACHE_PATH, {})
        if not isinstance(cache, dict):
            cache = {}

        TICKER_CACHE_STATE = (mtime, cache)
        return cache


def get_cached_mapping(ticker: str) -> dict[str, str] | None:
    cache = load_ticker_cache()
    item = cache.get(ticker)
    if not isinstance(item, dict):
        return None

    sector = item.get("sector")
    industry = item.get("industry")
    updated_at = item.get("updated_at")
    if not isinstance(sector, str) or not sector:
        return None
    if not isinstance(industry, str) or not industry:
        return None
    if not isinstance(updated_at, str) or not updated_at:
        return None

    updated_dt = parse_iso8601(updated_at)
    if updated_dt is None:
        return None
    if datetime.now(timezone.utc) - updated_dt > TICKER_CACHE_TTL:
        return None

    return {"sector": sector, "industry": industry}


def update_cache_mapping(ticker: str, sector: str, industry: str) -> None:
    global TICKER_CACHE_STATE

    with file_lock(TICKER_CACHE_PATH):
        cache = load_json(TICKER_CACHE_PATH, {})
        if not isinstance(cache, dict):
            cache = {}
        cache[ticker] = {
            "sector": sector,
            "industry": industry,
            "updated_at": utcnow_iso(),
        }
        save_json(TICKER_CACHE_PATH, cache)
        try:
            mtime = TICKER_CACHE_PATH.stat().st_mtime
        except OSError:
            mtime = time.time()
        with TICKER_CACHE_LOCK:
            TICKER_CACHE_STATE = (mtime, cache)


def scrape_tradingview_ticker_mapping(ticker: str) -> dict[str, str] | None:
    for exchange in EXCHANGE_CANDIDATES:
        url = f"https://www.tradingview.com/symbols/{exchange}-{ticker}/"
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            continue
        if response.status_code != 200:
            time.sleep(0.1)
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        sector_link = soup.select_one('a[href*="/sectorandindustry-sector/"]')
        industry_link = soup.select_one('a[href*="/sectorandindustry-industry/"]')
        if not sector_link or not industry_link:
            continue

        sector = " ".join(sector_link.get_text(" ", strip=True).split()).strip()
        industry = " ".join(industry_link.get_text(" ", strip=True).split()).strip()
        if sector and industry:
            return {"sector": sector, "industry": industry}
    return None


def resolve_ticker_mapping(ticker: str) -> dict[str, str] | None:
    static_mapping = load_static_ticker_mapping()
    static_match = static_mapping.get(ticker)
    if static_match:
        return static_match

    cached = get_cached_mapping(ticker)
    if cached:
        return cached

    live = scrape_tradingview_ticker_mapping(ticker)
    if live:
        update_cache_mapping(ticker, live["sector"], live["industry"])
        return live

    return None


def get_current_ticker_state() -> dict[str, str | None]:
    state = load_json(CURRENT_TICKER_PATH, {})
    if not isinstance(state, dict):
        return {"ticker": None, "updated_at": None}
    ticker = state.get("ticker")
    updated_at = state.get("updated_at")
    return {
        "ticker": ticker if isinstance(ticker, str) else None,
        "updated_at": updated_at if isinstance(updated_at, str) else None,
    }


def set_current_ticker(raw_ticker: str) -> dict[str, str]:
    ticker = normalize_ticker(raw_ticker)
    if not ticker:
        raise ValueError("Invalid ticker")
    if ticker in NON_EQUITY_SYMBOLS or ticker in SYMBOL_PREFIXES:
        raise ValueError(f"Unsupported non-equity symbol: {ticker}")

    state = {"ticker": ticker, "updated_at": utcnow_iso()}
    with file_lock(CURRENT_TICKER_PATH):
        save_json(CURRENT_TICKER_PATH, state)
    return state


def get_stock_snapshot(raw_ticker: str) -> dict[str, Any]:
    normalized_ticker = normalize_ticker(raw_ticker)
    if not normalized_ticker:
        raise ValueError("Invalid ticker")

    mapping = resolve_ticker_mapping(normalized_ticker)
    if not mapping:
        raise LookupError(f"Mapping not found for ticker {normalized_ticker}")

    sectors_index, sectors_total = load_ranking_index(SECTORS_PATH, "sector")
    industries_index, industries_total = load_ranking_index(INDUSTRIES_PATH, "industry")

    sector_key = normalize_name(mapping["sector"])
    industry_key = normalize_name(mapping["industry"])
    sector_entry = sectors_index.get(sector_key)
    industry_entry = industries_index.get(industry_key)

    return {
        "ticker": normalized_ticker,
        "sector": mapping["sector"],
        "sector_rank": sector_entry.get("rank") if sector_entry else None,
        "sector_total": sectors_total,
        "sector_perf": sector_entry.get("performance") if sector_entry else None,
        "industry": mapping["industry"],
        "industry_rank": industry_entry.get("rank") if industry_entry else None,
        "industry_total": industries_total,
        "industry_perf": industry_entry.get("performance") if industry_entry else None,
    }
