"""Compatibility launcher for the ranking scraper."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    script_path = Path(__file__).parent / "scraper" / "scrape_rankings.py"
    runpy.run_path(str(script_path), run_name="__main__")
