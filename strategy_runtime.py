"""In-process strategy state, intraday breakout flow, trailing SL ladder, and order events."""

from __future__ import annotations

import csv
import hashlib
import os
import threading
import time as time_mod
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import FyresIntegration as fyers_integration
import fyers_client

IST = ZoneInfo("Asia/Kolkata")
TRADE_CSV_PATH = Path(__file__).resolve().parent / "TradeSettings.csv"
MAX_ORDER_EVENTS = 1500
LEVEL_BUFFER_POINTS = 3.0

_lock = threading.Lock()
_running = False
_connected = False
_last_message = ""
_positions: list[dict] = []
_hidden_ids: set[str] = set()
_order_events: list[dict[str, Any]] = []

_engine_thread: threading.Thread | None = None
_engine_stop = threading.Event()
_setting_states: list[dict] = []
_ws_thread: threading.Thread | None = None
_ws_last_signature: str = ""
_ws_retry_after_monotonic: float = 0.0


def _log(msg: str) -> None:
    print(f"[Strategy] {msg}", flush=True)


def _now_ist() -> datetime:
    return datetime.now(IST)


def _set_message(msg: str) -> None:
    global _last_message
    with _lock:
        _last_message = msg


def _position_id(symbol: str, idx: int) -> str:
    h = hashlib.sha256(f"{symbol}|{idx}".encode()).hexdigest()
    return h[:20]


def _safe_int(v: str | int | float, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _to_json_safe(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v) for v in value]
    return str(value)


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


def _parse_expiry_code(expires_on: str, exp_type: str = "") -> str:
    s = str(expires_on or "").strip()
    if not s:
        return ""
    _ = str(exp_type or "").strip().upper()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            # Example: 28-04-2026 -> 26APR (format seen in Fyers search).
            return d.strftime("%y%b").upper()
        except ValueError:
            continue
    return ""


def _round_to_step(px: float, step: int) -> int:
    if step <= 0:
        step = 50
    return int(round(px / step) * step)


def _is_market_closed_for_row(now_ist: datetime, squareoff_time: time) -> bool:
    """
    Market-closed window requested by user:
    if time is greater than square-off time and less than 09:15 (next session open),
    strategy start should be blocked.
    """
    t = now_ist.time()
    return t >= squareoff_time or t < time(9, 15)


def _is_market_open_for_row(now_ist: datetime, squareoff_time: time) -> bool:
    return not _is_market_closed_for_row(now_ist, squareoff_time)


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


def _append_order_event(
    message: str,
    kind: str = "info",
    symbol: str = "",
    pnl: float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    global _order_events
    now = _now_ist()
    evt = {
        "ts": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "iso": now.isoformat(timespec="seconds"),
        "message": str(message),
        "kind": kind or "info",
        "symbol": str(symbol or "").strip(),
        "pnl": None if pnl is None else round(_safe_float(pnl), 2),
        "details": _to_json_safe(details or {}),
    }
    with _lock:
        _order_events.append(evt)
        if len(_order_events) > MAX_ORDER_EVENTS:
            _order_events = _order_events[-MAX_ORDER_EVENTS:]


def get_order_events() -> list[dict[str, Any]]:
    with _lock:
        return list(_order_events)


def _price_from_quotes(symbol: str) -> float | None:
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
    global _ws_thread, _ws_last_signature, _ws_retry_after_monotonic
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
    signature = "|".join(sym_list)
    now_mono = time_mod.monotonic()
    # Prevent tight reconnect loops when symbols are invalid/rejected.
    if signature == _ws_last_signature and now_mono < _ws_retry_after_monotonic:
        return
    _ws_last_signature = signature
    _ws_retry_after_monotonic = now_mono + 30.0
    _log(f"Starting options websocket for {len(sym_list)} symbols.")
    _set_message(
        "Subscribing option symbols on websocket: "
        + ", ".join(sym_list[:2])
        + ("..." if len(sym_list) > 2 else "")
    )
    _ws_thread = threading.Thread(
        target=fyers_integration.fyres_websocket_option,
        args=(sym_list,),
        name="options-websocket",
        daemon=True,
    )
    _ws_thread.start()


def _fetch_candle_value(symbol: str, target_dt: datetime, field: str) -> float | None:
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
    ex = (exchange or "NSE").strip().upper()
    bs = (base_symbol or "").strip().upper()
    if not bs or not expiry_code:
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
        exp_type = val("EXPTYPE")
        expiry_code = _parse_expiry_code(val("EXPIERYDATE"), exp_type)
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
                    "cum_realised": 0.0,
                },
            }
        )
    if not out:
        return [], (
            "No active settings: set TRADINGENABLED=TRUE for at least one row in TradeSettings.csv "
            "and click Load set before Start strategy."
        )
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
        "or add fy_id, pin, totpkey, client_id, secret_key, redirect_uri for automatic login."
    )


def _prepare_contracts_for_day(st: dict, now: datetime) -> None:
    s = st["state"]
    if s["prepared"] or now.time() < time(9, 30):
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
        candle_dt = datetime.combine(now.date(), tr, tzinfo=IST)
        ce_high = _fetch_candle_value(s["ce_symbol"], candle_dt, "high")
        pe_high = _fetch_candle_value(s["pe_symbol"], candle_dt, "high")
        ce_low = _fetch_candle_value(s["ce_symbol"], candle_dt, "low")
        pe_low = _fetch_candle_value(s["pe_symbol"], candle_dt, "low")
        if ce_high is None or pe_high is None:
            _log(f"Row {st['row_index']}: missing highs for window {tr.strftime('%H:%M')}.")
            s["processed_windows"].add(idx)
            return
        ce_breakout = ce_high + LEVEL_BUFFER_POINTS
        pe_breakout = pe_high + LEVEL_BUFFER_POINTS
        ce_low_buffered = None if ce_low is None else ce_low - LEVEL_BUFFER_POINTS
        pe_low_buffered = None if pe_low is None else pe_low - LEVEL_BUFFER_POINTS
        s["active_trigger"] = {
            "window_index": idx,
            "window_time": tr,
            "ce_high": ce_high,
            "pe_high": pe_high,
            "ce_low": ce_low,
            "pe_low": pe_low,
            "ce_breakout": ce_breakout,
            "pe_breakout": pe_breakout,
            "ce_low_buffered": ce_low_buffered,
            "pe_low_buffered": pe_low_buffered,
        }
        s["processed_windows"].add(idx)
        _log(
            f"Row {st['row_index']}: window {tr.strftime('%H:%M')} armed. "
            f"CE H/L {ce_high:.2f}/{_safe_float(ce_low):.2f}, PE H/L {pe_high:.2f}/{_safe_float(pe_low):.2f}, "
            f"buffer={LEVEL_BUFFER_POINTS:.2f} -> CE breakout {ce_breakout:.2f}, PE breakout {pe_breakout:.2f}"
        )
        return


def _place_order(symbol: str, qty: int, side: int, order_type: int = 2, price: float = 0.0) -> tuple[bool, dict[str, Any]]:
    req = {
        "symbol": symbol,
        "quantity": int(qty),
        "type": int(order_type),
        "side": int(side),
        "price": float(price),
    }
    try:
        r = fyers_integration.place_order(
            symbol=req["symbol"],
            quantity=req["quantity"],
            type=req["type"],
            side=req["side"],
            price=req["price"],
        )
    except Exception as e:
        return False, {"request": req, "response": str(e), "message": str(e), "order_id": ""}
    if isinstance(r, dict) and r.get("s") == "ok":
        return True, {
            "request": req,
            "response": r,
            "message": str(r.get("message") or r.get("msg") or "ok"),
            "order_id": str(r.get("id") or ""),
        }
    if isinstance(r, dict):
        return False, {
            "request": req,
            "response": r,
            "message": str(r.get("message") or r.get("msg") or r),
            "order_id": "",
        }
    return False, {"request": req, "response": r, "message": "Order rejected", "order_id": ""}


def _place_buy(symbol: str, qty: int) -> tuple[bool, dict[str, Any]]:
    return _place_order(symbol=symbol, qty=qty, side=1, order_type=2, price=0.0)


def _place_squareoff(symbol: str, qty: int) -> tuple[bool, dict[str, Any]]:
    return _place_order(symbol=symbol, qty=qty, side=-1, order_type=2, price=0.0)


def _next_trigger_r(current: float) -> float:
    if current < 1.0:
        return 1.5
    return round(current + 0.5, 2)


def _round_rr_label(level_r: float) -> str:
    return f"{level_r:g}"


def _compute_target_levels(entry: float, risk: float, count: int = 10) -> list[dict[str, float]]:
    levels: list[dict[str, float]] = []
    lvl = 1.0
    for _ in range(max(0, count)):
        price = entry + risk * lvl
        levels.append({"rr": lvl, "price": price})
        lvl = round(lvl + 0.5, 2)
    return levels


def _trail_sl_for_trigger(entry: float, risk: float, trigger_r: float, current_sl: float) -> float:
    # As requested:
    # 1:1   -> trail SL to +3% from entry
    # 1:1.5 -> trail SL to 1:0.5
    # 1:2   -> trail SL to 1:1
    # ...and so on (increase by +0.5R for every +0.5R trigger)
    if trigger_r <= 1.0:
        candidate = entry * 1.03
    else:
        sl_rr = max(0.5, trigger_r - 1.0)
        candidate = entry + risk * sl_rr
    return max(current_sl, candidate)


def _close_internal_position(st: dict, now: datetime, reason: str, market_price: float | None = None) -> bool:
    s = st["state"]
    pos = s.get("open_position")
    if not pos:
        return False
    exit_price = _safe_float(market_price, pos["entry_price"])
    stop_at_exit = _safe_float(pos.get("stop_price"))
    ok, meta = _place_squareoff(pos["symbol"], int(pos["qty"]))
    is_paper_pos = bool(pos.get("paper_position"))
    if not ok and not is_paper_pos:
        info = str(meta.get("message") or "Exit failed")
        _log(f"Row {st['row_index']}: exit failed ({reason}) for {pos['symbol']}: {info}")
        _set_message(f"Exit failed ({reason}) row {st['row_index']}: {info}")
        _append_order_event(
            f"ORDER EXIT FAIL {pos['symbol']} reason={reason} qty={pos['qty']} err={info}",
            kind="warn",
            symbol=pos["symbol"],
            details={
                "action": "SELL",
                "order_type": "MARKET",
                "reason": reason,
                "request": meta.get("request"),
                "response": meta.get("response"),
                "qty": int(pos["qty"]),
            },
        )
        return False
    broker_rejected_info = ""
    if not ok and is_paper_pos:
        broker_rejected_info = str(meta.get("message") or "Exit broker rejected; closing locally")

    realised = (exit_price - pos["entry_price"]) * pos["qty"]
    s["cum_realised"] = _safe_float(s.get("cum_realised"), 0.0) + realised
    s["open_position"] = None
    s["entry_done"] = False
    s["active_trigger"] = None

    msg = (
        f"EXIT {reason} {pos['symbol']} qty={pos['qty']} "
        f"entry={pos['entry_price']:.2f} exit={exit_price:.2f} "
        f"sl_at_exit={stop_at_exit:.2f} realised={realised:.2f}"
    )
    _append_order_event(
        (
            f"ORDER EXIT {pos['symbol']} reason={reason} qty={pos['qty']} "
            f"entry={pos['entry_price']:.2f} exit={exit_price:.2f} "
            f"sl_at_exit={stop_at_exit:.2f} target_at_exit={_safe_float(pos.get('target_price')):.2f}"
            + (f" broker_rejected={broker_rejected_info}" if broker_rejected_info else "")
        ),
        kind="warn" if broker_rejected_info else "info",
        symbol=pos["symbol"],
        pnl=realised,
        details={
            "action": "SELL",
            "order_type": "MARKET",
            "reason": reason,
            "request": meta.get("request"),
            "response": meta.get("response"),
            "qty": int(pos["qty"]),
            "entry_price": round(_safe_float(pos["entry_price"]), 4),
            "exit_price": round(exit_price, 4),
            "stop_price_at_exit": round(stop_at_exit, 4),
            "target_price_at_exit": round(_safe_float(pos.get("target_price")), 4),
            "paper_position": is_paper_pos,
            "broker_rejected": broker_rejected_info if broker_rejected_info else None,
            "cum_realised_after_exit": round(_safe_float(s.get("cum_realised")), 4),
            "total_pnl_after_exit": round(_safe_float(s.get("cum_realised")), 4),
        },
    )
    _set_message(msg)
    _log(msg)
    return True


def _check_and_enter(st: dict, now: datetime) -> None:
    s = st["state"]
    trigger = s.get("active_trigger")
    if not trigger or s["entry_done"]:
        return
    ce_ltp = _price_from_quotes(s["ce_symbol"])
    pe_ltp = _price_from_quotes(s["pe_symbol"])
    if ce_ltp is None and pe_ltp is None:
        return

    chosen_symbol = ""
    chosen_ltp = 0.0
    chosen_low = None
    if ce_ltp is not None and ce_ltp > _safe_float(trigger.get("ce_breakout"), trigger["ce_high"]):
        chosen_symbol = s["ce_symbol"]
        chosen_ltp = ce_ltp
        chosen_low = trigger.get("ce_low_buffered")
    elif pe_ltp is not None and pe_ltp > _safe_float(trigger.get("pe_breakout"), trigger["pe_high"]):
        chosen_symbol = s["pe_symbol"]
        chosen_ltp = pe_ltp
        chosen_low = trigger.get("pe_low_buffered")
    if not chosen_symbol:
        return

    ok, meta = _place_buy(chosen_symbol, st["quantity"])
    is_paper_position = not ok

    entry = max(0.01, _safe_float(chosen_ltp, 0.01))
    stop = _safe_float(chosen_low, 0.0)
    if stop <= 0 or stop >= entry:
        stop = entry * (1.0 - 0.0245)
    risk = entry - stop
    if risk <= 0:
        stop = entry * (1.0 - 0.0245)
        risk = max(0.01, entry - stop)

    s["entry_done"] = True
    s["open_position"] = {
        "symbol": chosen_symbol,
        "qty": st["quantity"],
        "entered_at": now,
        "window_time": trigger["window_time"].strftime("%H:%M"),
        "entry_price": entry,
        "stop_price": stop,
        "risk": risk,
        "next_trigger_r": 1.0,
        "target_price": entry + risk * 1.0,
        "highest_price": entry,
        "order_id": str(meta.get("order_id") or ""),
        "paper_position": is_paper_position,
    }
    level_rows = _compute_target_levels(entry, risk, count=10)
    levels_msg = ", ".join(
        [f"1:{_round_rr_label(row['rr'])}={row['price']:.2f}" for row in level_rows]
    )
    _log(
        f"Row {st['row_index']}: entry target levels (next 10) for {chosen_symbol}: {levels_msg}"
    )

    if is_paper_position:
        err = str(meta.get("message") or "entry failed")
        emsg = (
            f"ENTRY PAPER {chosen_symbol} qty={st['quantity']} @ {entry:.2f} "
            f"SL={stop:.2f} target(1:1.0)={entry + risk * 1.0:.2f} broker_rejected={err}"
        )
        kind = "warn"
    else:
        emsg = (
            f"ENTRY {chosen_symbol} qty={st['quantity']} @ {entry:.2f} "
            f"SL={stop:.2f} target(1:1.0)={entry + risk * 1.0:.2f}"
        )
        kind = "info"
    _append_order_event(
        (
            f"ORDER ENTRY {chosen_symbol} qty={st['quantity']} entry={entry:.2f} "
            f"initial_sl={stop:.2f} initial_target={entry + risk * 1.0:.2f}"
            + (f" broker_rejected={str(meta.get('message') or 'entry failed')}" if is_paper_position else "")
        ),
        kind=kind,
        symbol=chosen_symbol,
        details={
            "action": "BUY",
            "order_type": "MARKET",
            "reason": "ENTRY_BREAKOUT",
            "request": meta.get("request"),
            "response": meta.get("response"),
            "qty": int(st["quantity"]),
            "entry_price": round(entry, 4),
            "initial_stop_price": round(stop, 4),
            "initial_target_price": round(entry + risk * 1.0, 4),
            "current_stop_price": round(stop, 4),
            "current_target_price": round(entry + risk * 1.0, 4),
            "paper_position": is_paper_position,
            "breakout_price": round(
                _safe_float(
                    trigger.get(
                        "ce_breakout" if chosen_symbol == s["ce_symbol"] else "pe_breakout",
                        0.0,
                    )
                ),
                4,
            ),
            "next_10_target_levels": [
                {"rr": f"1:{_round_rr_label(row['rr'])}", "price": round(row["price"], 4)}
                for row in level_rows
            ],
        },
    )
    _set_message(emsg)
    _log(emsg)


def _manage_open_position(st: dict, now: datetime) -> None:
    s = st["state"]
    pos = s.get("open_position")
    if not pos:
        return

    ltp = _price_from_quotes(pos["symbol"])
    if ltp is None:
        return
    pos["highest_price"] = max(_safe_float(pos.get("highest_price")), ltp)

    current_sl = _safe_float(pos["stop_price"])
    if ltp <= current_sl:
        _close_internal_position(st, now, "SL_HIT", market_price=ltp)
        return

    entry = _safe_float(pos["entry_price"])
    risk = max(0.01, _safe_float(pos["risk"], 0.01))
    trigger_r = _safe_float(pos["next_trigger_r"], 1.0)

    while ltp >= entry + risk * trigger_r:
        new_sl = _trail_sl_for_trigger(entry, risk, trigger_r, _safe_float(pos["stop_price"]))
        pos["stop_price"] = new_sl
        next_r = trigger_r + 0.5
        pos["target_price"] = entry + risk * next_r
        pos["next_trigger_r"] = _next_trigger_r(trigger_r)
        achieved_level = f"1:{_round_rr_label(trigger_r)}"

        tmsg = (
            f"TSL UPDATE {pos['symbol']} level {achieved_level} -> "
            f"new_tsl={new_sl:.2f}, new_target={_safe_float(pos['target_price']):.2f}"
        )
        _append_order_event(
            (
                f"ORDER TSL UPDATE {pos['symbol']} level={achieved_level} "
                f"new_tsl={new_sl:.2f} new_target={_safe_float(pos['target_price']):.2f}"
            ),
            kind="info",
            symbol=pos["symbol"],
            details={
                "action": "HOLD",
                "order_type": "TSL",
                "qty": int(pos["qty"]),
                "reason": f"tsl_level_1:{trigger_r:.1f}_hit",
                "entry_price": round(entry, 4),
                "new_stop_price": round(new_sl, 4),
                "next_target_price": round(_safe_float(pos["target_price"]), 4),
                "current_stop_price": round(new_sl, 4),
                "current_target_price": round(_safe_float(pos["target_price"]), 4),
                "achieved_level": achieved_level,
            },
        )
        _set_message(tmsg)
        _log(tmsg)
        trigger_r = _safe_float(pos["next_trigger_r"])


def _squareoff_due(st: dict, now: datetime) -> None:
    s = st["state"]
    sq = st["squareoff_time"]
    if now.time() < sq or s.get("squareoff_done"):
        return
    s["squareoff_done"] = True
    pos = s.get("open_position")
    if not pos:
        _log(f"Row {st['row_index']}: no open position at square-off {sq.strftime('%H:%M')}.")
        _append_order_event(
            f"ORDER SQUAREOFF CHECK row={st['row_index']} no_open_position at {sq.strftime('%H:%M')}",
            kind="info",
            details={"reason": "SQUAREOFF_TIME", "row_index": st["row_index"]},
        )
        return
    ltp = _price_from_quotes(pos["symbol"])
    _close_internal_position(st, now, "SQUAREOFF_TIME", market_price=ltp)


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
    s["cum_realised"] = 0.0


def _engine_loop() -> None:
    global _connected
    _log("Engine loop started.")
    while not _engine_stop.is_set():
        now = _now_ist()
        for st in _setting_states:
            if not _is_market_open_for_row(now, st["squareoff_time"]):
                continue
            _reset_state_for_new_day(st, now.date())
            _prepare_contracts_for_day(st, now)
        _start_option_websocket_if_needed()
        for st in _setting_states:
            _squareoff_due(st, now)
            if not _is_market_open_for_row(now, st["squareoff_time"]):
                continue
            _activate_window_if_due(st, now)
            _check_and_enter(st, now)
            _manage_open_position(st, now)
        with _lock:
            _connected = True
        time_mod.sleep(1.0)
    _log("Engine loop stopped.")


def get_status() -> dict:
    with _lock:
        return {"running": _running, "connected": _connected, "message": _last_message}


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
                    "timestamp": _now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
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

    now_ist = _now_ist()
    waiting_for_market_open = all(_is_market_closed_for_row(now_ist, st["squareoff_time"]) for st in settings)

    _setting_states = settings
    _engine_stop.clear()
    _engine_thread = threading.Thread(target=_engine_loop, name="strategy-engine", daemon=True)
    _engine_thread.start()

    with _lock:
        _running = True
        _connected = True
        _last_message = (
            "Waiting for market to open (09:15 IST to SqaureoffTime)."
            if waiting_for_market_open
            else (
                f"Strategy running for {len(_setting_states)} setting(s). "
                "Trailing SL active; square-off at SqaureoffTime."
            )
        )
        _hidden_ids.clear()
        _positions = []
    _append_order_event("Strategy started.", kind="info")
    _log(_last_message)
    return True, _last_message


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
    _append_order_event("Strategy stopped.", kind="info")
    return True, "Strategy stopped."


def refresh_positions() -> list[dict]:
    global _positions
    dry = os.environ.get("STRATEGY_ALLOW_DRY_RUN", "").strip() in ("1", "true", "yes")
    with _lock:
        if not _running:
            return []
        hidden = set(_hidden_ids)

    if dry:
        with _lock:
            now = _now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
            for p in _positions:
                p["timestamp"] = now
            return [p for p in _positions if p["id"] not in hidden]

    out: list[dict] = []
    now_ist = _now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    for st in _setting_states:
        s = st["state"]
        pos = s.get("open_position")
        if not pos:
            continue
        sym = pos["symbol"]
        pid = _position_id(sym, st["row_index"])
        if pid in hidden:
            continue
        ltp = _price_from_quotes(sym)
        entry = _safe_float(pos["entry_price"])
        qty = int(pos["qty"])
        unreal = 0.0 if ltp is None else (ltp - entry) * qty
        realised = _safe_float(s.get("cum_realised"))
        total_pnl = realised + unreal
        invested = abs(entry * qty) if entry and qty else 0.0
        unreal_pct = f"{(unreal / invested * 100):.2f}%" if invested > 0 else "—"
        total_pct = f"{(total_pnl / invested * 100):.2f}%" if invested > 0 else "—"
        out.append(
            {
                "id": pid,
                "timestamp": now_ist,
                "symbolname": sym,
                "realisedpnl": round(realised, 2),
                "unrealisedpnl_pct": unreal_pct,
                "unrealisedpnl_pts": round(unreal, 2),
                "totalpnl": round(total_pnl, 2),
                "totalpnl_pct": total_pct,
                "currentsl": round(_safe_float(pos.get("stop_price")), 2),
                "currenttarget": round(_safe_float(pos.get("target_price")), 2),
                "paperposition": bool(pos.get("paper_position")),
            }
        )

    with _lock:
        _positions = out
        return [p for p in out if p["id"] not in hidden]


def exit_position(position_id: str) -> tuple[bool, str]:
    with _lock:
        if not _running:
            return False, "Strategy is not running."
        _hidden_ids.add(position_id)
    return True, "Position hidden in dashboard. Square off in Fyers if you still hold the leg."
