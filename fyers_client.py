"""Minimal Fyers API v3 helpers (profile + positions)."""

from __future__ import annotations

import os
from typing import Any

import requests

FYERS_BASE = "https://api-t1.fyers.in/api/v3"


def get_credentials() -> tuple[str, str]:
    app_id = os.environ.get("FYERS_APP_ID", "").strip()
    token = os.environ.get("FYERS_ACCESS_TOKEN", "").strip()
    return app_id, token


def _headers(app_id: str, token: str) -> dict[str, str]:
    return {"Authorization": f"{app_id}:{token}"}


def verify_session(app_id: str, token: str) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    if not app_id or not token:
        return False, "Set environment variables FYERS_APP_ID and FYERS_ACCESS_TOKEN (from Fyers API login)."
    try:
        r = requests.get(
            f"{FYERS_BASE}/profile",
            headers=_headers(app_id, token),
            timeout=20,
        )
    except requests.RequestException as e:
        return False, f"Network error: {e}"
    try:
        data = r.json()
    except ValueError:
        return False, f"Invalid response ({r.status_code})"
    if r.status_code != 200:
        return False, data.get("message") or data.get("msg") or r.text[:200]
    if data.get("s") != "ok":
        return False, data.get("message") or data.get("msg") or "Profile check failed"
    return True, ""


def fetch_net_positions(app_id: str, token: str) -> tuple[list[dict[str, Any]], str]:
    """Return (positions_list, error_message). positions_list empty on error."""
    try:
        r = requests.get(
            f"{FYERS_BASE}/positions",
            headers=_headers(app_id, token),
            timeout=20,
        )
    except requests.RequestException as e:
        return [], str(e)
    try:
        data = r.json()
    except ValueError:
        return [], f"Invalid JSON ({r.status_code})"
    if data.get("s") != "ok":
        return [], data.get("message") or data.get("msg") or "Positions request failed"

    raw = data.get("netPositions") or data.get("net_positions") or []
    if not isinstance(raw, list):
        return [], "Unexpected positions payload"

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        sym = (
            row.get("symbol")
            or row.get("tradingsymbol")
            or row.get("fyToken")
            or f"row-{idx}"
        )
        sym = str(sym)

        def _f(*keys: str, default: float = 0.0) -> float:
            for k in keys:
                v = row.get(k)
                if v is None or v == "":
                    continue
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
            return default

        realised = _f("realized_profit", "realized_pl", "booked_pl", "realizedProfit")
        unreal_pts = _f("unrealized_profit", "unrealized_pl", "pl", "unrealizedProfit")
        qty = _f("qty", "netQty", "net_qty", default=0.0)
        avg = _f("avg_price", "avgPrice", "net_avg", default=0.0)

        invested = abs(qty) * avg if avg and qty else 0.0
        if invested > 0 and unreal_pts != 0:
            unreal_pct = f"{(unreal_pts / invested * 100):.2f}%"
        else:
            unreal_pct = "—"

        out.append(
            {
                "symbolname": sym,
                "realisedpnl": round(realised, 2),
                "unrealisedpnl_pts": round(unreal_pts, 2),
                "unrealisedpnl_pct": unreal_pct,
                "_source_index": idx,
            }
        )
    return out, ""
