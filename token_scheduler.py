"""Background Fyers login ~09:15 IST daily: refreshes access_token in CSV, closes websocket.

Runs whenever the Flask app is up — independent of Start/Stop strategy.

Disable with environment variable: DISABLE_FYERS_TOKEN_SCHEDULER=1
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, time as time_cls
from zoneinfo import ZoneInfo

import FyresIntegration as fyers_integration
import fyers_client
import strategy_runtime

IST = ZoneInfo("Asia/Kolkata")
WINDOW_START = time_cls(9, 15)
WINDOW_END = time_cls(9, 30)
CHECK_INTERVAL_SEC = 15
ATTEMPT_GAP_SEC = 90.0

_token_refresh_date: date | None = None
_last_attempt_mono: float = 0.0
_scheduler_started = False
_scheduler_lock = threading.Lock()


def _daily_token_refresh_tick() -> None:
    global _token_refresh_date, _last_attempt_mono

    now = datetime.now(IST)
    d = now.date()
    t = now.time()
    if not (WINDOW_START <= t < WINDOW_END):
        return
    if _token_refresh_date == d:
        return

    store = fyers_client.load_credentials_store()
    if not fyers_client.store_has_auto_login_fields(store):
        return

    mono = time.monotonic()
    if mono - _last_attempt_mono < ATTEMPT_GAP_SEC:
        return
    _last_attempt_mono = mono

    tok, err = fyers_integration.run_automated_login_from_store(store)
    if tok:
        fyers_client.save_access_token_to_csv(str(tok))
        _token_refresh_date = d
        strategy_runtime.reset_after_scheduled_token_refresh()
        strategy_runtime.append_order_event_scheduled(
            "Fyers access token refreshed (daily ~09:15 IST, background scheduler). "
            "Saved to FyersCredentials.csv; option websocket closed if it was open.",
            kind="info",
        )
        print("[TokenScheduler] Daily Fyers login OK; token saved.", flush=True)
        return

    print(f"[TokenScheduler] Daily Fyers login failed: {err}", flush=True)
    strategy_runtime.append_order_event_scheduled(f"Scheduled token refresh failed: {err}", kind="warn")


def _scheduler_loop() -> None:
    while True:
        try:
            if os.environ.get("DISABLE_FYERS_TOKEN_SCHEDULER", "").strip().lower() not in (
                "1",
                "true",
                "yes",
                "on",
            ):
                _daily_token_refresh_tick()
        except Exception as e:
            print(f"[TokenScheduler] Error: {e}", flush=True)
        time.sleep(CHECK_INTERVAL_SEC)


def start_daily_token_scheduler() -> None:
    """Start daemon thread once per process (safe if called multiple times)."""
    global _scheduler_started
    if os.environ.get("DISABLE_FYERS_TOKEN_SCHEDULER", "").strip().lower() in ("1", "true", "yes", "on"):
        print("[TokenScheduler] Disabled via DISABLE_FYERS_TOKEN_SCHEDULER.", flush=True)
        return
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="fyers-daily-token")
    t.start()
    print(
        "[TokenScheduler] Started: daily token refresh ~09:15–09:30 IST "
        "(runs without pressing Start strategy).",
        flush=True,
    )
