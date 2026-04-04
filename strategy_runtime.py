"""In-process strategy run state, Fyers connection, and net positions cache."""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime, timezone

import fyers_client

_lock = threading.Lock()
_running = False
_connected = False
_last_message = ""
_positions: list[dict] = []
_hidden_ids: set[str] = set()


def _position_id(symbol: str, idx: int) -> str:
    h = hashlib.sha256(f"{symbol}|{idx}".encode()).hexdigest()
    return h[:20]


def get_status() -> dict:
    with _lock:
        return {
            "running": _running,
            "connected": _connected,
            "message": _last_message,
        }


def start_strategy() -> tuple[bool, str]:
    global _running, _connected, _last_message, _positions, _hidden_ids
    dry = os.environ.get("STRATEGY_ALLOW_DRY_RUN", "").strip() in ("1", "true", "yes")

    with _lock:
        if _running:
            return False, "Strategy is already running."

    app_id, token = fyers_client.get_credentials()
    if dry:
        with _lock:
            _running = True
            _connected = True
            _last_message = "Dry run (STRATEGY_ALLOW_DRY_RUN): mock data for UI testing."
            _hidden_ids.clear()
            _positions = [
                {
                    "id": "dry-run-demo",
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "symbolname": "DEMO:MOCK-EQ",
                    "realisedpnl": 0.0,
                    "unrealisedpnl_pct": "1.25%",
                    "unrealisedpnl_pts": 125.5,
                }
            ]
        return True, _last_message

    ok, err = fyers_client.verify_session(app_id, token)
    if not ok:
        with _lock:
            _running = False
            _connected = False
            _last_message = err
        return False, err

    pos, perr = fyers_client.fetch_net_positions(app_id, token)
    with _lock:
        _running = True
        _connected = True
        _last_message = perr or "Connected to Fyers."
        _hidden_ids.clear()
        _positions = _normalize_positions(pos)

    return True, _last_message


def _normalize_positions(rows: list[dict]) -> list[dict]:
    out = []
    for i, r in enumerate(rows):
        sym = str(r.get("symbolname", ""))
        pid = _position_id(sym, int(r.get("_source_index", i)))
        out.append(
            {
                "id": pid,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "symbolname": sym,
                "realisedpnl": r.get("realisedpnl", 0),
                "unrealisedpnl_pct": r.get("unrealisedpnl_pct", "—"),
                "unrealisedpnl_pts": r.get("unrealisedpnl_pts", 0),
            }
        )
    return out


def stop_strategy() -> tuple[bool, str]:
    global _running, _connected, _last_message, _positions, _hidden_ids
    with _lock:
        _running = False
        _connected = False
        _last_message = "Strategy stopped."
        _positions = []
        _hidden_ids.clear()
    return True, "Strategy stopped."


def refresh_positions() -> list[dict]:
    """Call while running to pull latest from Fyers (or keep dry-run list)."""
    global _positions, _last_message, _connected
    dry = os.environ.get("STRATEGY_ALLOW_DRY_RUN", "").strip() in ("1", "true", "yes")

    with _lock:
        if not _running:
            return []
        hidden = set(_hidden_ids)

    if dry:
        with _lock:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            for p in _positions:
                p["timestamp"] = now
            return [p for p in _positions if p["id"] not in hidden]

    app_id, token = fyers_client.get_credentials()
    ok, err = fyers_client.verify_session(app_id, token)
    if not ok:
        with _lock:
            _connected = False
            _last_message = err
            return [p for p in _positions if p["id"] not in hidden]

    rows, perr = fyers_client.fetch_net_positions(app_id, token)
    fresh = _normalize_positions(rows)
    with _lock:
        _connected = True
        if perr:
            _last_message = perr
        _positions = fresh
        return [p for p in _positions if p["id"] not in hidden]


def exit_position(position_id: str) -> tuple[bool, str]:
    """Hide position in UI until strategy stops. Does not place a broker square-off order."""
    with _lock:
        if not _running:
            return False, "Strategy is not running."
        _hidden_ids.add(position_id)
    return True, "Position hidden in dashboard. Square off in Fyers if you still hold the leg."

