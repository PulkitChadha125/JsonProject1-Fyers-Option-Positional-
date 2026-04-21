# Trading strategy dashboard

A Flask dashboard for:

- managing trade settings from `TradeSettings.csv`
- starting/stopping an intraday breakout strategy with Fyers
- monitoring live net positions
- viewing order/app logs

UI is dark (black/charcoal + yellow accents) and mobile-friendly with a collapsible sidebar.

## Features

### Symbol settings (`/`)

- CSV-backed settings table with sticky key columns (`SYMBOL`, `TRADING`, `ACTIONS`) on desktop.
- Schema-driven UI: columns are rendered directly from `TradeSettings.csv` headers.
- `TRADINGENABLED` toggle updates CSV immediately via API.
- Edit modal for full row update.
- Time-friendly modal inputs for any header containing `time` (for example: `TimeRage1`, `TimeRage2`, `TimeRage3`, `SqaureoffTime`).
- Add/delete row support.

### Strategy controls (`/`)

- Start/Stop strategy buttons with live status badge.
- Start initializes Fyers session, loads enabled settings, and starts the runtime loop.
- Runtime follows configured `TimeRage*` windows and enforces square-off at `SqaureoffTime`.

### Live net positions

- Polled while strategy is running.
- Displays timestamp, symbol, realised P&L, unrealised %, unrealised points.
- Exit button currently hides the row in dashboard view.

### Logs

- Order log (`/order-log`): localStorage-backed with filters (all/symbol/today/custom range).
- App log (`/app-log`): localStorage-backed activity log.
- Clear actions for both logs.

## Requirements

- Python 3.10+
- Dependencies in `requirements.txt`:
  - Flask
  - requests
  - fyers-apiv3
  - pyotp
  - pandas
  - pytz

## Setup

Run from project root (folder containing `app.py` and `TradeSettings.csv`).

### Windows (PowerShell)

```powershell
cd "d:\Desktop\python projects\JsonProject1"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS / Linux

```bash
cd /path/to/JsonProject1
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Fyers credentials (`FyersCredentials.csv`)

Expected two columns: `Title,Value`.

Required for auto-login flow:

- `client_id`
- `secret_key`
- `redirect_uri`
- `FY_ID`
- `PIN`
- `totpkey`

Optional:

- `access_token` (reused if valid; refreshed and written back when auto-login succeeds)
- `state`

Environment overrides (optional):

- `FYERS_APP_ID`
- `FYERS_ACCESS_TOKEN`

Security note: `FyersCredentials.csv` is ignored in `.gitignore` and should never be committed.

## Strategy runtime flow (implemented)

When strategy is started and at least one row has `TRADINGENABLED=TRUE`:

1. Login/verify Fyers session.
2. Load active rows from `TradeSettings.csv`.
3. For each active row (per day):
   - from 9:30 onward, read 9:15 candle open of `Symbol` on 15m timeframe,
   - round to nearest `StrikeStep`,
   - construct CE/PE option symbols using `BaseSymbol` + `ExpieryDate` + rounded strike,
   - subscribe option symbols to websocket,
   - at each `TimeRage` + 15 minutes, mark CE/PE candle highs,
   - take buy entry on first breakout (one active position per setting at a time),
   - detect manual close and allow later windows if position is no longer open,
   - at `SqaureoffTime`, square off all open broker positions.

Current scope intentionally does not include full target/TSL implementation yet.

## Run

```bash
python app.py
```

Open <http://127.0.0.1:5000>.

Other pages:

- <http://127.0.0.1:5000/net-position>
- <http://127.0.0.1:5000/order-log>
- <http://127.0.0.1:5000/app-log>

## Environment flags

- `STRATEGY_ALLOW_DRY_RUN=1`: runs mock mode for UI validation without real broker actions.

## `TradeSettings.csv` notes

- Header is dynamic; UI and API follow whatever columns are present.
- `TRADINGENABLED` column is required for strategy activation toggle.
- Empty trailing lines are ignored.
- Current expected strategy columns include:
  - `Symbol`
  - `BaseSymbol`
  - `Quantity`
  - `StrikeStep`
  - `TimeRage1`
  - `TimeRage2`
  - `TimeRage3`
  - `SqaureoffTime`
  - `Target`
  - `StopLoss`
  - `ExpieryDate`
  - `ExpType`
  - `TRADINGENABLED`

## HTTP API

All endpoints return JSON.

Settings:

- `GET /api/settings`
- `POST /api/settings`
- `PUT /api/settings/<index>`
- `PATCH /api/settings/<index>/trading`
- `DELETE /api/settings/<index>`

Strategy + positions:

- `GET /api/strategy/status`
- `POST /api/strategy/start`
- `POST /api/strategy/stop`
- `GET /api/net-positions`
- `POST /api/net-positions/<position_id>/exit`

## Project layout

```text
JsonProject1/
├── app.py
├── strategy_runtime.py
├── fyers_client.py
├── FyresIntegration.py
├── requirements.txt
├── TradeSettings.csv
├── FyersCredentials.csv
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── net_position.html
│   ├── order_log.html
│   └── app_log.html
└── static/
    ├── css/style.css
    └── js/
        ├── common.js
        ├── layout.js
        ├── settings.js
        ├── order_log_page.js
        └── app_log_page.js
```

## License

No license file is included yet.
