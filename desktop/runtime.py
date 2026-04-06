from __future__ import annotations

import os
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
    APP_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TradingSectorPanel"
else:
    BUNDLE_DIR = SOURCE_ROOT
    APP_HOME = SOURCE_ROOT

DATA_DIR = APP_HOME / "data"
BUNDLED_DATA_DIR = BUNDLE_DIR / "data"


def configure_import_path() -> None:
    for import_root in (SOURCE_ROOT, BUNDLE_DIR):
        import_path = str(import_root)
        if import_path not in sys.path:
            sys.path.insert(0, import_path)


def configure_runtime_environment() -> None:
    configure_import_path()
    os.environ["TSI_DATA_DIR"] = str(DATA_DIR)


configure_runtime_environment()
