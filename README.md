# Trading strategy dashboard

A small **Flask** web app for editing per-symbol trade settings stored in **`TradeSettings.csv`**. The UI uses a dark, Binance-style palette (black/charcoal surfaces, yellow accents, compact inputs).

Navigation is a **left sidebar** with separate pages: **Symbol settings**, **Net position**, **Order log**, and **App log**.

## Features

### Symbol settings (`/`)

- Settings appear as a **scrollable table** with one row per CSV record.
- **View mode** (default): cells are read-only text. The **`TRADINGENABLED`** column shows a True/False badge; the **Trading** column has a circular **toggle** (play-style) that updates the CSV immediately via the API.
- **Edit** (pencil): opens the modal with one field per CSV column. Any column named **`StartTime`** or **`StopTime`** uses a time picker. If the CSV has two `StartTime` headers, the second is labeled **Start time (2)**.
- **Save** writes the row to `TradeSettings.csv`; **Cancel** discards edits for that row.
- **Delete** (trash) removes the row after confirmation.
- **Add new setting** appends a blank row and opens it in edit mode (default `TRADINGENABLED` is `FALSE`).

### Other pages

- **Net position** (`/net-position`): placeholder until a strategy engine feeds live data.
- **Order log** (`/order-log`): stored in **localStorage**; symbol settings actions are recorded with the row’s **Symbol**. Filters: **All logs**, **Symbol** (dropdown), **Today**, **Custom range** (date from/to). **Clear order log** wipes stored entries for this browser.
- **App log** (`/app-log`): dashboard activity in **localStorage**. **Clear app log** removes all entries for this browser.

## Requirements

- Python 3.10+ (recommended; the code uses modern `list[str]` typing).
- Dependencies are listed in `requirements.txt` (Flask 3.x).

## Setup

Create a virtual environment, install packages, then run the app from the project root (the folder that contains `app.py` and `TradeSettings.csv`).

**Windows (PowerShell):**

```powershell
cd "d:\Desktop\python projects\JsonProject1"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux:**

```bash
cd /path/to/JsonProject1
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Fyers API (Start strategy)

**Start strategy** checks your Fyers session and then polls **net positions** for the live table.

Set these environment variables before running the app (values come from the Fyers API dashboard after you complete their login / token flow):

| Variable | Purpose |
|----------|---------|
| `FYERS_APP_ID` | Your Fyers app / client id (e.g. `XXXXXX-100`) |
| `FYERS_ACCESS_TOKEN` | Valid access token for API v3 |

Optional:

| Variable | Purpose |
|----------|---------|
| `STRATEGY_ALLOW_DRY_RUN` | Set to `1` to start without Fyers and show a **mock** position (UI testing only). |

**Exit** on the net-position row only **hides** that line in the dashboard until you stop the strategy; it does **not** send a square-off order to Fyers (that can be added later).

## Run

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

Use the sidebar to open [http://127.0.0.1:5000/net-position](http://127.0.0.1:5000/net-position), [http://127.0.0.1:5000/order-log](http://127.0.0.1:5000/order-log), and [http://127.0.0.1:5000/app-log](http://127.0.0.1:5000/app-log).

The dev server runs with `debug=True` on `127.0.0.1:5000` as defined in `app.py`. For production, use a proper WSGI server and turn off debug mode.

## Data file: `TradeSettings.csv`

- The first row is the **header**. All data rows must have the same number of columns as the header (the app pads or trims when reading).
- A column named **`TRADINGENABLED`** (case-insensitive) is required for the trading toggle. Values are normalized to `TRUE` or `FALSE`.
- Completely empty lines after the header are ignored.

Example header (your file may differ):

`Symbol`, `BaseSymbol`, `Quantity`, `StrikeRange`, `StrikeStep`, `StartTime`, `Target`, `StopLoss`, `ExpieryDate`, `ExpType`, `TradeType`, `TRADINGENABLED` (add or remove columns by editing the header row; use **Load set** to refresh the UI.)

## HTTP API

All API routes return JSON unless noted.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings` | Returns `{ "headers": [...], "rows": [[...], ...] }`. |
| `POST` | `/api/settings` | Optional body `{ "values": [...] }`. Appends a row; omit `values` for an empty row. |
| `PUT` | `/api/settings/<index>` | Body `{ "values": [...] }`. Replaces row at zero-based `index`. |
| `PATCH` | `/api/settings/<index>/trading` | Body `{ "enabled": true \| false }`. Updates `TRADINGENABLED` only. |
| `DELETE` | `/api/settings/<index>` | Removes the row at `index`. |

## Project layout

```
JsonProject1/
├── app.py
├── requirements.txt
├── TradeSettings.csv
├── templates/
│   ├── base.html           # Sidebar layout
│   ├── index.html          # Symbol settings (table)
│   ├── net_position.html
│   ├── order_log.html
│   └── app_log.html
└── static/
    ├── css/style.css
    └── js/
        ├── common.js       # Toasts + log storage helpers
        ├── settings.js     # Symbol table + API
        ├── app_log_page.js
        └── order_log_page.js
```

## License

Add a license file if you plan to distribute the project; none is included by default.
