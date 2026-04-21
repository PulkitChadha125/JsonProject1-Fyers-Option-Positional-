"""In-process strategy state, intraday breakout flow, and positions cache."""

from __future__ import annotations

import csv
import hashlib
import os
import threading
import time as time_mod
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import FyresIntegration as fyers_integration
import fyers_client

IST = ZoneInfo("Asia/Kolkata")
TRADE_CSV_PATH = Path(__file__).resolve().parent / "TradeSettings.csv"

_lock = threading.Lock()
_running = False
_connected = False
_last_message = ""
_positions: list[dict] = []
_hidden_ids: set[str] = set()

_engine_thread: threading.Thread | None = None
_engine_stop = threading.Event()
_setting_states: list[dict] = []
_ws_thread: threading.Thread | None = None


def _log(msg: str) -> None:
    print(f"[Strategy] {msg}", flush=True)


def _now_ist() -> datetime:
    return datetime.now(IST)


def _position_id(symbol: str, idx: int) -> str:
    h = hashlib.sha256(f"{symbol}|{idx}".encode()).hexdigest()
    return h[:20]


def _safe_int(v: str | int | float, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _parse_bool(v: str) -> bool:
    return str(v or "").strip().upper() in ("TRUE", "1", "YES", "ON")


def _parse_hhmm(v: str) -> time | None:
    s = str(v or "").strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) < 2:
        return None
    try:
        hh = max(0, min(23, int(parts[0])))
        mm = max(0, min(59, int(parts[1])))
    except ValueError:
        return None
    return time(hour=hh, minute=mm)


def _parse_expiry_code(expires_on: str) -> str:
    """19-03-2026 -> 19MAR."""
    s = str(expires_on or "").strip()
    if not s:
        return ""
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.strftime("%d%b").upper()
        except ValueError:
            continue
    return ""


def _round_to_step(px: float, step: int) -> int:
    if step <= 0:
        step = 50
    return int(round(px / step) * step)


def _with_ist(ts) -> datetime | None:
    if ts is None:
        return None
    try:
        dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    except Exception:
        dt = ts
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def _price_from_quotes(symbol: str) -> float | None:
    # Prefer websocket ticks if available.
    try:
        ws_ltp = fyers_integration.shared_data_2.get(symbol)
        if ws_ltp is not None:
            return float(ws_ltp)
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        q = fyers_integration.fyres_quote(symbol)
    except Exception:
        return None
    if not isinstance(q, dict):
        return None
    rows = q.get("d")
    if not isinstance(rows, list) or not rows:
        return None
    v = rows[0].get("v") if isinstance(rows[0], dict) else None
    if not isinstance(v, dict):
        return None
    try:
        return float(v.get("lp"))
    except (TypeError, ValueError):
        return None


def _start_option_websocket_if_needed() -> None:
    global _ws_thread
    if _ws_thread and _ws_thread.is_alive():
        return
    symbols: set[str] = set()
    for st in _setting_states:
        s = st["state"]
        if s.get("prepared"):
            if s.get("ce_symbol"):
                symbols.add(s["ce_symbol"])
            if s.get("pe_symbol"):
                symbols.add(s["pe_symbol"])
    if not symbols:
        return
    sym_list = sorted(symbols)
    _log(f"Starting options websocket for {len(sym_list)} symbols.")
    _ws_thread = threading.Thread(
        target=fyers_integration.fyres_websocket_option,
        args=(sym_list,),
        name="options-websocket",
        daemon=True,
    )
    _ws_thread.start()


def _fetch_candle_value(symbol: str, target_dt: datetime, field: str) -> float | None:
    """
    Return OHLC field from 15m candle that starts exactly at target_dt (IST).
    field: one of open/high/low/close.
    """
    try:
        df = fyers_integration.fetchOHLC(symbol, 15)
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    cols = {c.lower(): c for c in list(df.columns)}
    fc = cols.get(field.lower())
    dc = cols.get("date")
    if not fc or not dc:
        return None

    tday = target_dt.date()
    for _, row in df.iterrows():
        dt = _with_ist(row[dc])
        if dt is None:
            continue
        if dt.date() == tday and dt.hour == target_dt.hour and dt.minute == target_dt.minute:
            try:
                return float(row[fc])
            except (TypeError, ValueError):
                return None
    return None


def _build_option_symbol(exchange: str, base_symbol: str, expiry_code: str, strike: int, side: str) -> str:
    """NSE + NIFTY + 19MAR + 23450 + CE/PE -> NSE:NIFTY19MAR23450CE."""
    ex = (exchange or "NSE").strip().upper()
    bs = (base_symbol or "").strip().upper()
    if not bs:
        return ""
    if not expiry_code:
        return ""
    return f"{ex}:{bs}{expiry_code}{int(strike)}{side.upper()}"


def _load_active_settings() -> tuple[list[dict], str]:
    if not TRADE_CSV_PATH.is_file():
        return [], "TradeSettings.csv not found."
    try:
        with TRADE_CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    except OSError as e:
        return [], f"Could not read TradeSettings.csv: {e}"
    if not rows:
        return [], "TradeSettings.csv is empty."

    hdr = [str(x or "").strip() for x in rows[0]]
    idx = {h.upper(): i for i, h in enumerate(hdr)}
    required = ("SYMBOL", "BASESYMBOL", "QUANTITY", "STRIKESTEP", "EXPIERYDATE")
    missing = [k for k in required if k not in idx]
    if missing:
        return [], "Missing required columns: " + ", ".join(missing)

    out: list[dict] = []
    for ri, rr in enumerate(rows[1:], start=1):
        if not any((c or "").strip() for c in rr):
            continue

        def val(col: str) -> str:
            i = idx.get(col.upper(), -1)
            return rr[i].strip() if i >= 0 and i < len(rr) else ""

        enabled = _parse_bool(val("TRADINGENABLED")) if "TRADINGENABLED" in idx else False
        if not enabled:
            continue

        sym = val("SYMBOL")
        base = val("BASESYMBOL")
        qty = _safe_int(val("QUANTITY"), 0)
        step = _safe_int(val("STRIKESTEP"), 50)
        sq_time = _parse_hhmm(val("SQAUREOFFTIME") or val("SQUAREOFFTIME")) or time(15, 10)
        t1 = _parse_hhmm(val("TIMERAGE1"))
        t2 = _parse_hhmm(val("TIMERAGE2"))
        t3 = _parse_hhmm(val("TIMERAGE3"))
        ranges = [x for x in (t1, t2, t3) if x is not None]
        expiry_code = _parse_expiry_code(val("EXPIERYDATE"))
        if not sym or not base or qty <= 0 or not ranges or not expiry_code:
            continue

        exchange = "NSE"
        if ":" in sym:
            exchange = sym.split(":", 1)[0].strip().upper() or "NSE"

        out.append(
            {
                "row_index": ri,
                "symbol": sym,
                "base_symbol": base,
                "exchange": exchange,
                "quantity": qty,
                "strike_step": step,
                "time_ranges": ranges,
                "squareoff_time": sq_time,
                "expiry_code": expiry_code,
                "state": {
                    "for_date": None,
                    "prepared": False,
                    "ce_symbol": "",
                    "pe_symbol": "",
                    "entry_done": False,
                    "open_position": None,
                    "processed_windows": set(),
                    "active_trigger": None,
                    "squareoff_done": False,
                },
            }
        )
    if not out:
        return [], "No TRADINGENABLED=TRUE rows found in TradeSettings.csv."
    return out, ""


def _connect_fyers(store: dict) -> tuple[bool, str]:
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


def _prepare_contracts_for_day(st: dict, now: datetime) -> None:
    s = st["state"]
    if s["prepared"]:
        return
    # Prepare from 9:30 onward using the 9:15 candle open of the configured symbol.
    if now.time() < time(9, 30):
        return
    ref_dt = datetime.combine(now.date(), time(9, 15), tzinfo=IST)
    open_px = _fetch_candle_value(st["symbol"], ref_dt, "open")
    if open_px is None:
        return
    strike = _round_to_step(open_px, st["strike_step"])
    ce = _build_option_symbol(st["exchange"], st["base_symbol"], st["expiry_code"], strike, "CE")
    pe = _build_option_symbol(st["exchange"], st["base_symbol"], st["expiry_code"], strike, "PE")
    if not ce or not pe:
        return
    s["ce_symbol"] = ce
    s["pe_symbol"] = pe
    s["prepared"] = True
    _log(
        f"Row {st['row_index']}: prepared CE/PE from 9:15 open={open_px:.2f}, "
        f"strike={strike} -> {ce}, {pe}"
    )


def _activate_window_if_due(st: dict, now: datetime) -> None:
    s = st["state"]
    if not s["prepared"] or s["entry_done"]:
        return
    for idx, tr in enumerate(st["time_ranges"]):
        if idx in s["processed_windows"]:
            continue
        chk = datetime.combine(now.date(), tr, tzinfo=IST) + timedelta(minutes=15)
        if now < chk:
            continue
        ce_high = _fetch_candle_value(s["ce_symbol"], datetime.combine(now.date(), tr, tzinfo=IST), "high")
        pe_high = _fetch_candle_value(s["pe_symbol"], datetime.combine(now.date(), tr, tzinfo=IST), "high")
        if ce_high is None or pe_high is None:
            _log(f"Row {st['row_index']}: could not fetch highs for window {tr.strftime('%H:%M')}")
            s["processed_windows"].add(idx)
            return
        s["active_trigger"] = {
            "window_index": idx,
            "window_time": tr,
            "ce_high": ce_high,
            "pe_high": pe_high,
        }
        s["processed_windows"].add(idx)
        _log(
            f"Row {st['row_index']}: breakout armed for {tr.strftime('%H:%M')} "
            f"(check from {chk.strftime('%H:%M')}) CEhigh={ce_high:.2f} PEhigh={pe_high:.2f}"
        )
        return


def _place_buy(symbol: str, qty: int) -> tuple[bool, str]:
    try:
        r = fyers_integration.place_order(symbol=symbol, quantity=qty, type=2, side=1, price=0)
    except Exception as e:
        return False, str(e)
    if isinstance(r, dict) and r.get("s") == "ok":
        return True, str(r.get("id") or "")
    msg = ""
    if isinstance(r, dict):
        msg = str(r.get("message") or r.get("msg") or r)
    return False, msg or "Order rejected"


def _place_squareoff(symbol: str, qty: int) -> tuple[bool, str]:
    try:
        r = fyers_integration.place_order(symbol=symbol, quantity=qty, type=2, side=-1, price=0)
    except Exception as e:
        return False, str(e)
    if isinstance(r, dict) and r.get("s") == "ok":
        return True, str(r.get("id") or "")
    msg = ""
    if isinstance(r, dict):
        msg = str(r.get("message") or r.get("msg") or r)
    return False, msg or "Square-off rejected"


def _squareoff_all_open_positions() -> tuple[bool, str]:
    """
    Close all open net positions from broker view.
    qty > 0 -> sell side -1
    qty < 0 -> buy side 1
    """
    try:
        res = fyers_integration.get_position()
    except Exception as e:
        return False, str(e)
    if not isinstance(res, dict):
        return False, "Invalid positions payload"
    raw = res.get("netPositions") or []
    if not isinstance(raw, list):
        return False, "netPositions not found"

    closed = 0
    errors: list[str] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("tradingsymbol") or "").strip()
        if not sym:
            continue
        qv = row.get("qty") or row.get("netQty") or row.get("net_qty") or 0
        try:
            qty = int(abs(float(qv)))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        side = -1 if float(qv) > 0 else 1
        try:
            rr = fyers_integration.place_order(symbol=sym, quantity=qty, type=2, side=side, price=0)
            if isinstance(rr, dict) and rr.get("s") == "ok":
                closed += 1
            else:
                errors.append(f"{sym}: {rr}")
        except Exception as e:
            errors.append(f"{sym}: {e}")

    if errors:
        return False, "; ".join(errors[:4])
    return True, f"Square-off sent for {closed} position(s)."


def _check_and_enter(st: dict, now: datetime) -> None:
    s = st["state"]
    trigger = s.get("active_trigger")
    if not trigger or s["entry_done"]:
        return
    ce_ltp = _price_from_quotes(s["ce_symbol"])
    pe_ltp = _price_from_quotes(s["pe_symbol"])
    if ce_ltp is None and pe_ltp is None:
        return

    chosen = ""
    if ce_ltp is not None and ce_ltp > trigger["ce_high"]:
        chosen = s["ce_symbol"]
    elif pe_ltp is not None and pe_ltp > trigger["pe_high"]:
        chosen = s["pe_symbol"]
    if not chosen:
        return

    ok, info = _place_buy(chosen, st["quantity"])
    if not ok:
        _log(f"Row {st['row_index']}: entry order failed for {chosen}: {info}")
        return
    s["entry_done"] = True
    s["open_position"] = {
        "symbol": chosen,
        "qty": st["quantity"],
        "entered_at": now,
        "window_time": trigger["window_time"].strftime("%H:%M"),
        "order_id": info,
    }
    _set_message(
        f"Row {st['row_index']} entry: {chosen} breakout at {now.strftime('%H:%M:%S')} "
        f"(window {s['open_position']['window_time']})."
    )
    _log(_last_message)


def _check_manual_close(st: dict) -> None:
    s = st["state"]
    pos = s.get("open_position")
    if not pos:
        return
    try:
        res = fyers_integration.get_position()
    except Exception:
        return
    if not isinstance(res, dict):
        return
    raw = res.get("netPositions") or []
    still_open = False
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("tradingsymbol") or "")
        if sym != pos["symbol"]:
            continue
        qty = row.get("qty") or row.get("netQty") or row.get("net_qty") or 0
        try:
            if abs(float(qty)) > 0:
                still_open = True
                break
        except (TypeError, ValueError):
            continue
    if not still_open:
        _log(f"Row {st['row_index']}: detected external/manual close for {pos['symbol']}.")
        s["open_position"] = None
        s["entry_done"] = False
        s["active_trigger"] = None


def _squareoff_due(st: dict, now: datetime) -> None:
    s = st["state"]
    sq = st["squareoff_time"]
    if now.time() < sq or s.get("squareoff_done"):
        return
    ok, info = _squareoff_all_open_positions()
    s["squareoff_done"] = True
    if ok:
        _log(f"Row {st['row_index']}: {info} at {now.strftime('%H:%M:%S')}.")
        _set_message(f"Square-off executed at {sq.strftime('%H:%M')}. {info}")
        s["open_position"] = None
        s["entry_done"] = False
        s["active_trigger"] = None
    else:
        _log(f"Row {st['row_index']}: square-off failed for {pos['symbol']}: {info}")
        _set_message(f"Square-off failed for row {st['row_index']}: {info}")


def _reset_state_for_new_day(st: dict, d: date) -> None:
    s = st["state"]
    if s["for_date"] == d:
        return
    s["for_date"] = d
    s["prepared"] = False
    s["ce_symbol"] = ""
    s["pe_symbol"] = ""
    s["entry_done"] = False
    s["open_position"] = None
    s["processed_windows"] = set()
    s["active_trigger"] = None
    s["squareoff_done"] = False


def _engine_loop() -> None:
    global _connected
    _log("Engine loop started.")
    while not _engine_stop.is_set():
        now = _now_ist()
        for st in _setting_states:
            _reset_state_for_new_day(st, now.date())
            _prepare_contracts_for_day(st, now)
        _start_option_websocket_if_needed()
        for st in _setting_states:
            _check_manual_close(st)
            _activate_window_if_due(st, now)
            _check_and_enter(st, now)
            _squareoff_due(st, now)
        with _lock:
            _connected = True
        time_mod.sleep(1.0)
    _log("Engine loop stopped.")


def _set_message(msg: str) -> None:
    global _last_message
    with _lock:
        _last_message = msg


def get_status() -> dict:
    with _lock:
        return {
            "running": _running,
            "connected": _connected,
            "message": _last_message,
        }


def start_strategy() -> tuple[bool, str]:
    global _running, _connected, _last_message, _positions, _hidden_ids, _engine_thread, _setting_states
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

    settings, err = _load_active_settings()
    if not settings:
        with _lock:
            _running = False
            _connected = False
            _last_message = err or "No active trade settings found."
        return False, _last_message

    _setting_states = settings
    _engine_stop.clear()
    _engine_thread = threading.Thread(target=_engine_loop, name="strategy-engine", daemon=True)
    _engine_thread.start()

    res = fyers_integration.get_position()
    rows, perr = fyers_client.parse_positions_response(res if isinstance(res, dict) else {})
    with _lock:
        _running = True
        _connected = True
        _last_message = (
            perr
            or f"Strategy running for {len(_setting_states)} setting(s). "
            "Waiting for TimeRage windows and square-off at SqaureoffTime."
        )
        _hidden_ids.clear()
        _positions = _normalize_positions(rows)
    _log(_last_message)
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
    global _running, _connected, _last_message, _positions, _hidden_ids, _engine_thread
    _engine_stop.set()
    if _engine_thread and _engine_thread.is_alive():
        _engine_thread.join(timeout=2.0)
    _engine_thread = None

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
            tok2, _login_err = fyers_integration.run_automated_login_from_store(store)
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
