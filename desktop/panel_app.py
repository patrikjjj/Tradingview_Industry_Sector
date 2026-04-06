from __future__ import annotations

import argparse
import io
import json
import multiprocessing as mp
import os
import shutil
import sys
import threading
import tkinter as tk
import winreg
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from tkinter import ttk
from typing import Any

from desktop.runtime import APP_HOME, BUNDLED_DATA_DIR, DATA_DIR, SOURCE_ROOT
from core import market_data

REFRESH_MS = 1000
SCRAPER_INTERVAL_SECONDS = 60
NATIVE_HOST_NAME = "com.tradingsector.bridge"
EXTENSION_ID = "lklegpebjpffafgjpcnekcgnopnlfgki"
REGISTRY_TARGETS = (
    ("Chrome", r"Software\Google\Chrome\NativeMessagingHosts"),
    ("Edge", r"Software\Microsoft\Edge\NativeMessagingHosts"),
)
_DEVNULL_WRITER = None
_DEVNULL_LOCK = threading.Lock()


def prepare_runtime_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    seed_files = (
        ("tickers.csv", "ticker,sector,industry\n"),
        ("sectors.json", "[]"),
        ("industries.json", "[]"),
        ("current_ticker.json", '{"ticker": null, "updated_at": null}'),
        ("ticker_cache.json", "{}"),
    )
    for name, fallback in seed_files:
        destination = DATA_DIR / name
        if destination.exists():
            continue
        source = BUNDLED_DATA_DIR / name
        if source.exists():
            shutil.copy2(source, destination)
            continue
        destination.write_text(fallback, encoding="utf-8")


def get_devnull_writer():
    global _DEVNULL_WRITER
    with _DEVNULL_LOCK:
        if _DEVNULL_WRITER is None or _DEVNULL_WRITER.closed:
            _DEVNULL_WRITER = open(os.devnull, "w", encoding="utf-8", buffering=1)
        return _DEVNULL_WRITER


def ensure_stdio() -> None:
    devnull_writer = get_devnull_writer()
    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        sys.stdout = devnull_writer
    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        sys.stderr = devnull_writer
    if sys.stdin is None:
        sys.stdin = io.StringIO("")


def is_ranking_data_fresh(max_age_seconds: int = 180) -> bool:
    paths = (market_data.SECTORS_PATH, market_data.INDUSTRIES_PATH)
    try:
        mtimes = [path.stat().st_mtime for path in paths]
    except OSError:
        return False

    return all((datetime.now(timezone.utc).timestamp() - mtime) <= max_age_seconds for mtime in mtimes)


def resolve_native_host_command() -> str:
    if getattr(sys, "frozen", False):
        command_path = Path(sys.executable).with_name("TradingSectorNativeHost.exe")
    else:
        command_path = Path(sys.executable)
        script_path = SOURCE_ROOT / "desktop" / "native_host.py"
        return f'"{command_path}" "{script_path}"'
    return f'"{command_path}"'


def install_native_host() -> list[str]:
    host_dir = APP_HOME / "native-host"
    host_dir.mkdir(parents=True, exist_ok=True)

    launcher_path = host_dir / "launch_native_host.bat"
    launcher_path.write_text(f"@echo off\r\n{resolve_native_host_command()}\r\n", encoding="utf-8")

    manifest_path = host_dir / f"{NATIVE_HOST_NAME}.json"
    manifest = {
        "name": NATIVE_HOST_NAME,
        "description": "Trading sector desktop bridge",
        "path": str(launcher_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }
    market_data.save_json(manifest_path, manifest)

    registered_browsers: list[str] = []
    for browser_name, registry_root in REGISTRY_TARGETS:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{registry_root}\{NATIVE_HOST_NAME}") as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(manifest_path))
            registered_browsers.append(browser_name)
        except OSError:
            continue
    return registered_browsers


class ServiceManager:
    def __init__(self, autostart: bool = True) -> None:
        self.autostart = autostart
        self.scraper_process: mp.Process | None = None
        self.registered_browsers: list[str] = []

    def start(self) -> None:
        self.registered_browsers = install_native_host()
        if not self.autostart:
            return
        if not is_ranking_data_fresh():
            self.scraper_process = mp.Process(target=run_scraper_service, daemon=True)
            self.scraper_process.start()

    def stop(self) -> None:
        if self.scraper_process and self.scraper_process.is_alive():
            self.scraper_process.terminate()
            self.scraper_process.join(timeout=3)
            if self.scraper_process.is_alive():
                self.scraper_process.kill()
                self.scraper_process.join(timeout=1)



def run_scraper_service() -> None:
    ensure_stdio()
    from scraper.scrape_rankings import scrape_once

    while True:
        try:
            scrape_once()
        except Exception as exc:  # noqa: BLE001
            timestamp = datetime.now(timezone.utc).isoformat()
            print(f"[{timestamp}] scraper service failed: {exc}", file=sys.stderr)
        sleep(SCRAPER_INTERVAL_SECONDS)


class PanelApp:
    def __init__(self, root: tk.Tk, services: ServiceManager) -> None:
        self.root = root
        self.services = services
        self.root.title("Sector/Industry Panel")
        self.root.geometry("320x220")
        self.root.minsize(1, 1)
        self.root.resizable(True, True)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.active_ticker: str | None = None
        self.refresh_in_flight = False

        self.style = ttk.Style(root)
        self.style.configure("PerfPositive.TLabel", foreground="#1e8e3e")
        self.style.configure("PerfNegative.TLabel", foreground="#c62828")
        self.style.configure("PerfNeutral.TLabel", foreground="#52606d")
        self.style.configure("Status.TLabel", foreground="#54667a")

        frame = ttk.Frame(root, padding=8)
        frame.pack(fill="both", expand=True)

        self.ticker_var = tk.StringVar(value="-")
        self.sector_name_var = tk.StringVar(value="-")
        self.sector_rank_var = tk.StringVar(value="n/a")
        self.sector_perf_var = tk.StringVar(value="n/a")
        self.industry_name_var = tk.StringVar(value="-")
        self.industry_rank_var = tk.StringVar(value="n/a")
        self.industry_perf_var = tk.StringVar(value="n/a")
        self.status_var = tk.StringVar(value=self.initial_status())

        ttk.Label(frame, text="Ticker", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(frame, textvariable=self.ticker_var, font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w")

        sector_box = ttk.LabelFrame(frame, text="Sector", padding=6)
        sector_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 4))
        ttk.Label(sector_box, textvariable=self.sector_name_var, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(sector_box, textvariable=self.sector_rank_var).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.sector_perf_label = ttk.Label(sector_box, textvariable=self.sector_perf_var, style="PerfNeutral.TLabel")
        self.sector_perf_label.grid(row=2, column=0, sticky="w", pady=(1, 0))
        sector_box.columnconfigure(0, weight=1)
        sector_box.columnconfigure(1, weight=1)

        industry_box = ttk.LabelFrame(frame, text="Industry", padding=6)
        industry_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(industry_box, textvariable=self.industry_name_var, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(industry_box, textvariable=self.industry_rank_var).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.industry_perf_label = ttk.Label(industry_box, textvariable=self.industry_perf_var, style="PerfNeutral.TLabel")
        self.industry_perf_label.grid(row=2, column=0, sticky="w", pady=(1, 0))
        industry_box.columnconfigure(0, weight=1)
        industry_box.columnconfigure(1, weight=1)

        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self.schedule_refresh()

    def initial_status(self) -> str:
        if self.services.registered_browsers:
            browsers = ", ".join(self.services.registered_browsers)
            return f"Bridge ready for {browsers}"
        return "Bridge ready"

    def schedule_refresh(self) -> None:
        if not self.refresh_in_flight:
            self.refresh_in_flight = True
            threading.Thread(target=self.refresh_worker, daemon=True).start()
        self.root.after(REFRESH_MS, self.schedule_refresh)

    def refresh_worker(self) -> None:
        current_state: dict[str, str | None] = {"ticker": self.active_ticker, "updated_at": None}
        snapshot: dict[str, Any] | None = None
        error_message: str | None = None

        try:
            current_state = market_data.get_current_ticker_state()
            ticker = current_state.get("ticker")
            if isinstance(ticker, str) and ticker:
                try:
                    snapshot = market_data.get_stock_snapshot(ticker)
                except LookupError:
                    error_message = f"No mapping for {ticker}"
                except Exception as exc:  # noqa: BLE001
                    error_message = f"Update failed: {exc}"
        except Exception as exc:  # noqa: BLE001
            error_message = f"Update failed: {exc}"
        finally:
            try:
                self.root.after(0, lambda: self.apply_refresh_result(current_state, snapshot, error_message))
            except tk.TclError:
                self.refresh_in_flight = False

    @staticmethod
    def format_perf(value: Any) -> str:
        if value is None:
            return "Perf: n/a"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "Perf: n/a"
        prefix = "+" if numeric > 0 else ""
        return f"Perf: {prefix}{numeric:.2f}%"

    @staticmethod
    def format_rank(rank: Any, total: Any) -> str:
        if rank is None or total in (None, 0):
            return "Rank: n/a"
        return f"Rank: {rank} / {total}"

    @staticmethod
    def perf_style(value: Any) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "PerfNeutral.TLabel"
        if numeric > 0:
            return "PerfPositive.TLabel"
        if numeric < 0:
            return "PerfNegative.TLabel"
        return "PerfNeutral.TLabel"

    def render_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.ticker_var.set(snapshot.get("ticker", "-"))
        self.sector_name_var.set(snapshot.get("sector", "n/a"))
        self.sector_rank_var.set(self.format_rank(snapshot.get("sector_rank"), snapshot.get("sector_total")))
        sector_perf = snapshot.get("sector_perf")
        self.sector_perf_var.set(self.format_perf(sector_perf))
        self.sector_perf_label.configure(style=self.perf_style(sector_perf))

        self.industry_name_var.set(snapshot.get("industry", "n/a"))
        self.industry_rank_var.set(self.format_rank(snapshot.get("industry_rank"), snapshot.get("industry_total")))
        industry_perf = snapshot.get("industry_perf")
        self.industry_perf_var.set(self.format_perf(industry_perf))
        self.industry_perf_label.configure(style=self.perf_style(industry_perf))

    def apply_refresh_result(
        self,
        current_state: dict[str, str | None],
        snapshot: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        self.refresh_in_flight = False

        ticker = current_state.get("ticker")
        if isinstance(ticker, str) and ticker:
            self.active_ticker = ticker

        if snapshot:
            self.render_snapshot(snapshot)
            self.status_var.set(f"Updated {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
            return

        if error_message:
            if self.active_ticker:
                self.ticker_var.set(self.active_ticker)
            self.status_var.set(error_message)
            return

        if not self.active_ticker:
            self.status_var.set("Waiting for ticker from extension...")

    def on_close(self) -> None:
        self.services.stop()
        self.root.destroy()


def main() -> None:
    mp.freeze_support()
    prepare_runtime_data_dir()
    parser = argparse.ArgumentParser(description="Desktop sector/industry panel.")
    parser.add_argument("--no-autostart", action="store_true", help="Do not auto-start the scraper process.")
    args = parser.parse_args()

    services = ServiceManager(autostart=not args.no_autostart)
    services.start()

    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    PanelApp(root, services)
    root.mainloop()


if __name__ == "__main__":
    main()


