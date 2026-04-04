"""Fyers API v3 helpers: credentials from FyersCredentials.csv, optional auto-login."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import struct
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

FYERS_BASE = "https://api-t1.fyers.in/api/v3"
CREDENTIALS_PATH = Path(__file__).resolve().parent / "FyersCredentials.csv"


def _flow_log_enabled() -> bool:
    """Print login/API flow to the Flask terminal. Set FYERS_DEBUG_LOG=0 to disable."""
    v = os.environ.get("FYERS_DEBUG_LOG", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _flow_log(msg: str) -> None:
    if _flow_log_enabled():
        print(msg, flush=True)


def _deep_redact(o: Any) -> Any:
    """Redact secrets for terminal logging."""
    if isinstance(o, dict):
        out: dict[str, Any] = {}
        for k, v in o.items():
            lk = str(k).lower().replace("-", "_")
            if lk in (
                "access_token",
                "secret_key",
                "pin",
                "totpkey",
                "otp",
                "identifier",
                "authorization",
                "refresh_token",
            ):
                out[k] = "***"
            elif lk in ("code", "auth_code") and isinstance(v, str) and len(v) > 8:
                out[k] = f"{v[:8]}…<len {len(v)}>"
            elif lk == "appidhash" and isinstance(v, str) and len(v) > 12:
                out[k] = f"{v[:12]}…"
            elif lk == "fy_id" and isinstance(v, str):
                out[k] = "***" if len(v) > 2 else v
            elif lk == "request_key" and isinstance(v, str) and len(v) > 16:
                out[k] = f"{v[:8]}…{v[-4:]}"
            else:
                out[k] = _deep_redact(v)
        return out
    if isinstance(o, list):
        return [_deep_redact(x) for x in o[:80]]
    return o


def _format_body_for_log(body: str | dict | bytes | None) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8", errors="replace")
        except Exception:
            return "<bytes>"
    if isinstance(body, dict):
        try:
            return json.dumps(_deep_redact(body), indent=2)[:3500]
        except (TypeError, ValueError):
            return str(body)[:800]
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            return json.dumps(_deep_redact(parsed), indent=2)[:3500]
        except json.JSONDecodeError:
            return body[:1200]
    return str(body)[:800]


def _log_http_out(step: str, method: str, url: str, body: str | dict | bytes | None = None) -> None:
    if not _flow_log_enabled():
        return
    b = _format_body_for_log(body)
    _flow_log(f"[FyersFlow] >>> {step}\n    {method} {url}")
    if b.strip():
        _flow_log(f"    -- request body --\n{b}")


def _log_http_in(step: str, r: requests.Response, note: str = "") -> None:
    if not _flow_log_enabled():
        return
    extra = f" | {note}" if note else ""
    try:
        data = r.json()
        snippet = json.dumps(_deep_redact(data), indent=2)[:4000]
    except ValueError:
        snippet = (r.text or "")[:2000]
    _flow_log(f"[FyersFlow] <<< {step}{extra}\n    HTTP {r.status_code}\n{snippet}")


def load_credentials_store() -> dict[str, str]:
    """Read Title,Value pairs; keys lowercased."""
    if not CREDENTIALS_PATH.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        with CREDENTIALS_PATH.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                if len(row) < 2:
                    continue
                k = (row[0] or "").strip().lower()
                v = (row[1] or "").strip()
                if k:
                    out[k] = v
    except OSError:
        return {}
    return out


def save_access_token_to_csv(token: str) -> None:
    """Upsert row Title=access_token,Value=token. Preserves other rows."""
    token = (token or "").strip()
    if not token:
        return
    rows: list[list[str]] = []
    if CREDENTIALS_PATH.is_file():
        with CREDENTIALS_PATH.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    if not rows:
        rows = [["Title", "Value"]]
    header = rows[0]
    if len(header) < 2:
        header = ["Title", "Value"]
        rows[0] = header
    found = False
    for i in range(1, len(rows)):
        if len(rows[i]) >= 2 and (rows[i][0] or "").strip().lower() == "access_token":
            rows[i] = ["access_token", token]
            found = True
            break
    if not found:
        rows.append(["access_token", token])
    with CREDENTIALS_PATH.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def get_app_id(store: dict[str, str] | None = None) -> str:
    env = os.environ.get("FYERS_APP_ID", "").strip()
    if env:
        return env
    s = store if store is not None else load_credentials_store()
    return (s.get("client_id") or "").strip()


def get_access_token_from_store(store: dict[str, str] | None = None) -> str:
    env = os.environ.get("FYERS_ACCESS_TOKEN", "").strip()
    if env:
        return env
    s = store if store is not None else load_credentials_store()
    return (s.get("access_token") or "").strip()


def get_credentials() -> tuple[str, str]:
    store = load_credentials_store()
    return get_app_id(store), get_access_token_from_store(store)


def store_has_auto_login_fields(store: dict[str, str]) -> bool:
    need = ("fy_id", "pin", "totpkey", "client_id", "secret_key", "redirect_uri")
    return all((store.get(k) or "").strip() for k in need)


def _totp(secret: str, time_step: int = 30, digits: int = 6) -> str:
    key = secret.upper().replace(" ", "")
    pad = "=" * ((8 - len(key)) % 8)
    key = base64.b32decode(key + pad)
    counter = struct.pack(">Q", int(time.time() / time_step))
    mac = hmac.new(key, counter, "sha1").digest()
    offset = mac[-1] & 0x0F
    binary = struct.unpack(">L", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary)[-digits:].zfill(digits)


def _app_id_hash(client_id: str, secret_key: str) -> str:
    return hashlib.sha256(f"{client_id}:{secret_key}".encode()).hexdigest()


def _extract_access_token_from_validate_response(data: dict[str, Any]) -> str | None:
    if not isinstance(data, dict):
        return None
    tok = data.get("access_token")
    if tok:
        return str(tok)
    inner = data.get("data")
    if isinstance(inner, dict):
        tok = inner.get("access_token")
        if tok:
            return str(tok)
    return None


def exchange_auth_code_for_token(client_id: str, secret_key: str, auth_code: str) -> tuple[str | None, str]:
    app_hash = _app_id_hash(client_id, secret_key)
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_hash,
        "code": auth_code.strip(),
    }
    urls = (
        "https://api-t1.fyers.in/api/v3/validate-authcode",
        "https://api.fyers.in/api/v3/validate-authcode",
        "https://api-t1.fyers.in/api/v2/validate-authcode",
    )
    last_err = "Token exchange failed"
    for url in urls:
        try:
            _log_http_out("Step 5 validate-authcode", "POST", url, payload)
            r = requests.post(url, json=payload, timeout=30)
            _log_http_in("Step 5 validate-authcode", r, url)
            try:
                data = r.json()
            except ValueError:
                last_err = f"Invalid JSON from {url}"
                continue
            tok = _extract_access_token_from_validate_response(data)
            if tok:
                _flow_log("[FyersFlow] --- access_token received (value not printed) ---")
                return tok, ""
            last_err = data.get("message") or data.get("msg") or str(data)[:200]
        except requests.RequestException as e:
            last_err = str(e)
            _flow_log(f"[FyersFlow] !!! validate-authcode request error: {e}")
    return None, last_err


def programmatic_login_from_store(store: dict[str, str]) -> tuple[str | None, str]:
    """
    FY_ID + PIN + totpkey + client_id + secret_key + redirect_uri from CSV.
    Mirrors the common community flow (vagator OTP + Fyers token URL + validate-authcode).
    """
    if not store_has_auto_login_fields(store):
        return None, (
            "FyersCredentials.csv must include FY_ID, PIN, totpkey, client_id, "
            "secret_key, and redirect_uri for automatic login."
        )

    fy_id = store["fy_id"].strip()
    pin = store["pin"].strip()
    totp_key = store["totpkey"].strip()
    client_id = store["client_id"].strip()
    secret_key = store["secret_key"].strip()
    redirect_uri = store["redirect_uri"].strip()
    state = (store.get("state") or "sample").strip()

    if "-" in client_id:
        app_id_for_auth = client_id.rsplit("-", 1)[0]
    else:
        app_id_for_auth = client_id

    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (compatible; StrategyDashboard/1.0)",
    }
    s = requests.Session()
    s.headers.update(headers)

    _flow_log("[FyersFlow] ========== programmatic login start ==========")

    try:
        data1 = json.dumps(
            {
                "fy_id": base64.b64encode(fy_id.encode()).decode(),
                "app_id": "2",
            }
        )
        url1 = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
        _log_http_out("Step 1 send_login_otp_v2", "POST", url1, data1)
        r1 = s.post(url1, data=data1, timeout=30)
        _log_http_in("Step 1 send_login_otp_v2", r1)
        if r1.status_code != 200:
            return None, f"Fyers login step 1 HTTP {r1.status_code}: {r1.text[:300]}"
        body1 = r1.json()
        request_key = body1.get("request_key")
        if not request_key:
            return None, f"Fyers login step 1 failed: {body1}"

        otp = _totp(totp_key)
        data2 = json.dumps({"request_key": request_key, "otp": int(otp)})
        url2 = "https://api-t2.fyers.in/vagator/v2/verify_otp"
        _log_http_out("Step 2 verify_otp (TOTP)", "POST", url2, data2)
        r2 = s.post(url2, data=data2, timeout=30)
        _log_http_in("Step 2 verify_otp", r2)
        if r2.status_code != 200:
            return None, f"Fyers login step 2 HTTP {r2.status_code}: {r2.text[:300]}"
        body2 = r2.json()
        request_key = body2.get("request_key")
        if not request_key:
            return None, f"Fyers login step 2 failed: {body2}"

        data3 = json.dumps(
            {
                "request_key": request_key,
                "identity_type": "pin",
                "identifier": base64.b64encode(pin.encode()).decode(),
            }
        )
        url3 = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
        _log_http_out("Step 3 verify_pin_v2", "POST", url3, data3)
        r3 = s.post(url3, data=data3, timeout=30)
        _log_http_in("Step 3 verify_pin_v2", r3)
        if r3.status_code != 200:
            return None, f"Fyers login step 3 HTTP {r3.status_code}: {r3.text[:300]}"
        body3 = r3.json()
        bearer = (
            (body3.get("data") or {}).get("access_token")
            if isinstance(body3.get("data"), dict)
            else None
        )
        if not bearer:
            return None, f"Fyers PIN step failed: {body3}"

        data4 = json.dumps(
            {
                "fyers_id": fy_id,
                "app_id": app_id_for_auth,
                "redirect_uri": redirect_uri,
                "appType": "100",
                "code_challenge": "",
                "state": state,
                "scope": "",
                "nonce": "",
                "response_type": "code",
                "create_cookie": True,
            }
        )
        url4 = "https://api.fyers.in/api/v2/token"
        _flow_log(
            f"[FyersFlow] >>> Step 4 get auth code URL\n    POST {url4}\n"
            "    Header: Authorization: Bearer <redacted>"
        )
        _log_http_out("Step 4 body (JSON)", "POST", url4, data4)
        r4 = s.post(
            url4,
            headers={
                "authorization": f"Bearer {bearer}",
                "content-type": "application/json; charset=UTF-8",
            },
            data=data4,
            timeout=30,
        )
        _log_http_in("Step 4 api/v2/token (expect redirect URL in body)", r4)
        if r4.status_code not in (200, 308):
            try:
                detail = r4.json()
            except ValueError:
                detail = r4.text[:300]
            return None, f"Fyers auth code step failed ({r4.status_code}): {detail}"

        try:
            body4 = r4.json()
        except ValueError:
            return None, "Fyers auth code response was not JSON"

        url_str = body4.get("Url") or body4.get("url")
        if not url_str:
            return None, f"Fyers auth code missing redirect URL: {body4}"

        parsed = urlparse(url_str)
        qs = parse_qs(parsed.query)
        codes = qs.get("auth_code") or qs.get("code")
        if not codes:
            return None, f"No auth_code in redirect URL: {url_str[:200]}"
        auth_code = codes[0]
        _flow_log(
            f"[FyersFlow] --- parsed auth_code from redirect (prefix): {auth_code[:12]}… ---"
        )

        token, err = exchange_auth_code_for_token(client_id, secret_key, auth_code)
        if token:
            _flow_log("[FyersFlow] ========== programmatic login OK ==========")
            return token, ""
        _flow_log(f"[FyersFlow] ========== programmatic login FAILED: {err} ==========")
        return None, err or "validate-authcode did not return access_token"

    except requests.RequestException as e:
        _flow_log(f"[FyersFlow] ========== programmatic login FAILED (network): {e} ==========")
        return None, f"Fyers login network error: {e}"
    except (KeyError, TypeError, ValueError) as e:
        _flow_log(f"[FyersFlow] ========== programmatic login FAILED (parse): {e} ==========")
        return None, f"Fyers login parse error: {e}"


def ensure_access_token() -> tuple[str | None, str]:
    """
    Return (token, error). Uses CSV access_token / env, or runs programmatic login
    and saves token to CSV on success.
    """
    store = load_credentials_store()
    token = get_access_token_from_store(store)
    if token:
        src = "FYERS_ACCESS_TOKEN env" if os.environ.get("FYERS_ACCESS_TOKEN", "").strip() else "CSV/env access_token"
        _flow_log(f"[FyersFlow] Using existing token from {src} (not printed).")
        return token, ""

    _flow_log("[FyersFlow] No access_token in CSV/env; attempting programmatic login from CSV…")
    if store_has_auto_login_fields(store):
        tok, err = programmatic_login_from_store(store)
        if tok:
            save_access_token_to_csv(tok)
            _flow_log("[FyersFlow] Saved access_token row to FyersCredentials.csv")
            return tok, ""
        return None, err

    return None, (
        "No access token: add a row access_token,<token> to FyersCredentials.csv, "
        "or set FYERS_ACCESS_TOKEN, or complete FY_ID / PIN / totpkey / client_id / "
        "secret_key / redirect_uri for automatic login."
    )


def _headers(app_id: str, token: str) -> dict[str, str]:
    return {"Authorization": f"{app_id}:{token}"}


def verify_session(app_id: str, token: str) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    if not app_id or not token:
        return False, (
            "Missing Fyers app id or access token. Use FyersCredentials.csv "
            "(client_id + access_token or auto-login fields)."
        )
    try:
        prof_url = f"{FYERS_BASE}/profile"
        _log_http_out("verify_session profile", "GET", prof_url, None)
        _flow_log("    Header: Authorization: <client_id>:<access_token redacted>")
        r = requests.get(
            prof_url,
            headers=_headers(app_id, token),
            timeout=20,
        )
        _log_http_in("verify_session profile", r)
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
        pos_url = f"{FYERS_BASE}/positions"
        _log_http_out("fetch_net_positions", "GET", pos_url, None)
        r = requests.get(
            pos_url,
            headers=_headers(app_id, token),
            timeout=20,
        )
        _log_http_in("fetch_net_positions", r)
    except requests.RequestException as e:
        return [], str(e)
    try:
        data = r.json()
    except ValueError:
        return [], f"Invalid JSON ({r.status_code})"
    if data.get("s") != "ok":
        return [], data.get("message") or data.get("msg") or "Positions request failed"

    return parse_positions_response(data)


def parse_positions_response(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Normalize Fyers positions JSON (REST or fyers_apiv3 fyers.positions()) for the dashboard."""
    if not isinstance(data, dict):
        return [], "Invalid positions response"
    s = data.get("s")
    if s is not None and s != "ok":
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
