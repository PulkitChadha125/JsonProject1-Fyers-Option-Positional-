"""Flask dashboard for trade settings (CSV-backed)."""

from __future__ import annotations

import csv
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import strategy_runtime

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "TradeSettings.csv"

app = Flask(__name__)


def _read_csv() -> tuple[list[str], list[list[str]]]:
    if not CSV_PATH.is_file():
        return [], []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    headers = rows[0]
    data_rows = []
    for r in rows[1:]:
        if not any((c or "").strip() for c in r):
            continue
        w = len(headers)
        if len(r) < w:
            r = r + [""] * (w - len(r))
        elif len(r) > w:
            r = r[:w]
        data_rows.append(r)
    return headers, data_rows


def _write_csv(headers: list[str], data: list[list[str]]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(data)


def _trading_col_index(headers: list[str]) -> int:
    for i, h in enumerate(headers):
        if h.strip().upper() == "TRADINGENABLED":
            return i
    raise ValueError("CSV must include TRADINGENABLED column")


def _normalize_row(values: list[str], width: int) -> list[str]:
    row = [str(v).strip() if v is not None else "" for v in values]
    if len(row) < width:
        row.extend([""] * (width - len(row)))
    elif len(row) > width:
        row = row[:width]
    return row


def _default_empty_row(headers: list[str]) -> list[str]:
    out = [""] * len(headers)
    try:
        out[_trading_col_index(headers)] = "FALSE"
    except ValueError:
        pass
    return out


@app.route("/")
def index():
    return render_template("index.html", active_page="settings")


@app.route("/net-position")
def net_position():
    return render_template("net_position.html", active_page="net_position")


@app.route("/order-log")
def order_log():
    return render_template("order_log.html", active_page="order_log")


@app.route("/app-log")
def app_log():
    return render_template("app_log.html", active_page="app_log")


@app.get("/api/settings")
def api_settings_get():
    headers, rows = _read_csv()
    return jsonify({"headers": headers, "rows": rows})


@app.post("/api/settings")
def api_settings_add():
    headers, rows = _read_csv()
    if not headers:
        return jsonify({"error": "TradeSettings.csv has no header row"}), 400
    body = request.get_json(silent=True) or {}
    raw = body.get("values")
    if raw is None:
        new_row = _default_empty_row(headers)
    else:
        new_row = _normalize_row(list(raw), len(headers))
    try:
        ti = _trading_col_index(headers)
        te = new_row[ti].upper() or "FALSE"
        new_row[ti] = "TRUE" if te in ("TRUE", "1", "YES", "ON") else "FALSE"
    except ValueError:
        pass
    rows.append(new_row)
    _write_csv(headers, rows)
    return jsonify({"ok": True, "index": len(rows) - 1, "row": new_row})


@app.put("/api/settings/<int:row_index>")
def api_settings_update(row_index: int):
    headers, rows = _read_csv()
    if not headers or row_index < 0 or row_index >= len(rows):
        return jsonify({"error": "Invalid row index"}), 400
    body = request.get_json(silent=True) or {}
    raw = body.get("values")
    if not isinstance(raw, list):
        return jsonify({"error": "values must be a list"}), 400
    row = _normalize_row(raw, len(headers))
    try:
        ti = _trading_col_index(headers)
        te = row[ti].upper() or "FALSE"
        row[ti] = "TRUE" if te in ("TRUE", "1", "YES", "ON") else "FALSE"
    except ValueError:
        pass
    rows[row_index] = row
    _write_csv(headers, rows)
    return jsonify({"ok": True, "row": row})


@app.patch("/api/settings/<int:row_index>/trading")
def api_settings_toggle_trading(row_index: int):
    headers, rows = _read_csv()
    if not headers or row_index < 0 or row_index >= len(rows):
        return jsonify({"error": "Invalid row index"}), 400
    try:
        ti = _trading_col_index(headers)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled"))
    rows[row_index][ti] = "TRUE" if enabled else "FALSE"
    _write_csv(headers, rows)
    return jsonify({"ok": True, "enabled": enabled, "value": rows[row_index][ti]})


@app.delete("/api/settings/<int:row_index>")
def api_settings_delete(row_index: int):
    headers, rows = _read_csv()
    if row_index < 0 or row_index >= len(rows):
        return jsonify({"error": "Invalid row index"}), 400
    rows.pop(row_index)
    _write_csv(headers, rows)
    return jsonify({"ok": True})


@app.get("/api/strategy/status")
def api_strategy_status():
    return jsonify(strategy_runtime.get_status())


@app.post("/api/strategy/start")
def api_strategy_start():
    ok, msg = strategy_runtime.start_strategy()
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": msg, **strategy_runtime.get_status()}), status


@app.post("/api/strategy/stop")
def api_strategy_stop():
    ok, msg = strategy_runtime.stop_strategy()
    return jsonify({"ok": ok, "message": msg, **strategy_runtime.get_status()})


@app.get("/api/net-positions")
def api_net_positions():
    st = strategy_runtime.get_status()
    if not st["running"]:
        return jsonify({"positions": [], **st})
    positions = strategy_runtime.refresh_positions()
    return jsonify({"positions": positions, **strategy_runtime.get_status()})


@app.post("/api/net-positions/<position_id>/exit")
def api_net_position_exit(position_id: str):
    ok, msg = strategy_runtime.exit_position(position_id)
    st = strategy_runtime.get_status()
    positions = strategy_runtime.refresh_positions() if st["running"] else []
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": msg, "positions": positions, **st}), status


@app.get("/api/orders")
def api_orders():
    return jsonify({"orders": strategy_runtime.get_order_events()})


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
