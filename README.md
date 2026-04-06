# TradingView Sector/Industry Ranking Panel

Windows desktop companion for TradingView that captures the active ticker from a browser extension and shows sector and industry ranking context in a compact panel.

## What it does

- Tracks the active TradingView ticker through a browser extension and native messaging bridge.
- Scrapes TradingView USA sector rankings and industry rankings.
- Resolves ticker-to-sector and ticker-to-industry mappings with CSV fallback, local cache, and live lookup.
- Displays the current ticker, sector rank, industry rank, and performance in a desktop panel.

## Platform

- Windows only.
- Chrome and Edge are supported through native messaging registration under the current Windows user.

## Project layout

- `core/market_data.py`: local data access, ticker mapping, cache reads, and ranking lookups.
- `desktop/panel_app.py`: Tk desktop panel and browser native-host registration.
- `desktop/native_host.py`: native messaging bridge used by the extension.
- `desktop/build.bat`: maintainer build script for the packaged Windows app.
- `scraper/scrape_rankings.py`: ranking scraper loop.
- `extension/`: Chrome/Edge extension source.
- `data/tickers.csv`: bundled fallback ticker mapping seed.

## Distribution model

- This repository is the source project.
- `build/` and `dist/` are generated output and are not meant to be committed.
- End users should receive a packaged Windows zip from `dist/TradingSectorPanel/` and the extension as a separate zip.

## End-user setup

1. Download and unzip `TradingSectorPanel-windows.zip`.
2. Download and unzip the extension package.
3. Run `TradingSectorPanel.exe` once.
4. Open `chrome://extensions` or `edge://extensions`.
5. Enable Developer mode.
6. Choose `Load unpacked`.
7. Select the unzipped extension folder.

## Developer build

1. Install dependencies from `requirements.txt`.
2. Run `desktop\build.bat`.
3. Collect the packaged output from `dist\TradingSectorPanel\`.
4. Zip `dist\TradingSectorPanel\` for the desktop app release.
5. Zip `extension\` separately for the browser extension release.

## Notes
