from __future__ import annotations

import json
import struct
import sys

from desktop.runtime import DATA_DIR
from core import market_data


def read_message() -> dict | None:
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    if len(raw_length) != 4:
        raise EOFError("Incomplete native message length")

    message_length = struct.unpack("<I", raw_length)[0]
    payload = sys.stdin.buffer.read(message_length)
    if len(payload) != message_length:
        raise EOFError("Incomplete native message payload")
    return json.loads(payload.decode("utf-8"))


def write_message(message: dict) -> None:
    encoded = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def handle_message(message: dict) -> dict:
    if not isinstance(message, dict):
        return {"ok": False, "error": "Invalid payload"}

    message_type = message.get("type")
    if message_type == "ping":
        return {"ok": True}
    if message_type != "ticker":
        return {"ok": False, "error": "Unsupported message type"}

    ticker = message.get("ticker")
    if not isinstance(ticker, str):
        return {"ok": False, "error": "Ticker must be a string"}

    try:
        state = market_data.set_current_ticker(ticker)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "ticker": state["ticker"], "updated_at": state["updated_at"]}


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            message = read_message()
        except EOFError:
            break
        except (json.JSONDecodeError, UnicodeDecodeError):
            write_message({"ok": False, "error": "Invalid JSON payload"})
            continue
        if message is None:
            break
        write_message(handle_message(message))


if __name__ == "__main__":
    main()
