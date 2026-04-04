"""In-process strategy run state, Fyers connection, and net positions cache."""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime, timezone

import FyresIntegration as fyers_integration
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


def _connect_fyers(store: dict) -> tuple[bool, str]:
    """
    Prefer CSV/env access_token + FyersModel; on failure retry automated_login
    when CSV has FY_ID / PIN / totpkey / etc. (via FyresIntegration).
    """
    client_id = fyers_client.get_app_id(store)
    if not client_id:
        return False, "Missing client_id in FyersCredentials.csv (or FYERS_APP_ID)."

    token = fyers_client.get_access_token_from_store(store)
    if token:
        ok, err = fyers_integration.ensure_fyers_session(client_id, token)
        if ok:
            return True, ""
        if fyers_client.store_has_auto_login_fields(store):
            tok2, login_err = fyers_integration.run_automated_login_from_store(store)
            if tok2:
                fyers_client.save_access_token_to_csv(tok2)
                return fyers_integration.ensure_fyers_session(client_id, tok2)
            return False, login_err or err or "Auto-login failed after token rejection."
        return False, err or "Session invalid and CSV has no auto-login fields."

    if fyers_client.store_has_auto_login_fields(store):
        tok2, login_err = fyers_integration.run_automated_login_from_store(store)
        if not tok2:
            return False, login_err or "Automatic Fyers login failed."
        fyers_client.save_access_token_to_csv(tok2)
        return fyers_integration.ensure_fyers_session(client_id, tok2)

    return False, (
        "No access token: add access_token to FyersCredentials.csv, set FYERS_ACCESS_TOKEN, "
        "or add fy_id, pin, totpkey, client_id, secret_key, redirect_uri for auto-login."
    )


def start_strategy() -> tuple[bool, str]:
    global _running, _connected, _last_message, _positions, _hidden_ids
    dry = os.environ.get("STRATEGY_ALLOW_DRY_RUN", "").strip() in ("1", "true", "yes")

    with _lock:
        if _running:
            return False, "Strategy is already running."

    store = fyers_client.load_credentials_store()

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

    ok, conn_msg = _connect_fyers(store)
    if not ok:
        with _lock:
            _running = False
            _connected = False
            _last_message = conn_msg
        return False, _last_message

    res = fyers_integration.get_position()
    if not isinstance(res, dict):
        with _lock:
            _running = False
            _connected = False
            _last_message = "Invalid positions response from Fyers API."
        return False, _last_message

    rows, perr = fyers_client.parse_positions_response(res)
    with _lock:
        _running = True
        _connected = True
        _last_message = perr or "Connected to Fyers (fyers_apiv3)."
        _hidden_ids.clear()
        _positions = _normalize_positions(rows)

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

    ok, err = fyers_integration.verify_profile_ok()
    if not ok:
        store = fyers_client.load_credentials_store()
        client_id = fyers_client.get_app_id(store)
        if fyers_client.store_has_auto_login_fields(store):
            tok2, login_err = fyers_integration.run_automated_login_from_store(store)
            if tok2:
                fyers_client.save_access_token_to_csv(tok2)
                ok, err = fyers_integration.ensure_fyers_session(client_id, tok2)
        if not ok:
            with _lock:
                _connected = False
                _last_message = err
                return [p for p in _positions if p["id"] not in hidden]

    res = fyers_integration.get_position()
    if not isinstance(res, dict):
        with _lock:
            _connected = False
            _last_message = "Invalid positions response"
            return [p for p in _positions if p["id"] not in hidden]

    rows, perr = fyers_client.parse_positions_response(res)
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
