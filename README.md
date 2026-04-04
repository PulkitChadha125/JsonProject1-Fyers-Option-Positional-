# Trading strategy dashboard

A small **Flask** web app for editing per-symbol trade settings stored in **`TradeSettings.csv`**. The UI uses a dark theme with yellow accents: symbol cards, time pickers for schedule fields, and a single **Enabled / Disabled** control per row that maps to **`TRADINGENABLED`**.

**Net position** and **order log** are placeholder sections reserved for a future strategy engine.

## Features

- Load and display every column from `TradeSettings.csv` as editable fields on each row.
- **`StartTime`** and **`StopTime`** columns use HTML time inputs (24-hour). If the CSV has two `StartTime` headers, the second appears as **Start time (2)** in the UI.
- **Add setting** appends a new blank row (default `TRADINGENABLED` is `FALSE`).
- **Delete** removes a row after confirmation.
- **Enabled / Disabled** toggles `TRADINGENABLED` immediately (`TRUE` / `FALSE` in the file).
- **Save row** writes the rest of the fields for that index back to the CSV.
- **App log** shows basic client-side activity (load, save, toggle, add, delete).

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

## Run

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

The dev server runs with `debug=True` on `127.0.0.1:5000` as defined in `app.py`. For production, use a proper WSGI server and turn off debug mode.

## Data file: `TradeSettings.csv`

- The first row is the **header**. All data rows must have the same number of columns as the header (the app pads or trims when reading).
- A column named **`TRADINGENABLED`** (case-insensitive) is required for the trading toggle. Values are normalized to `TRUE` or `FALSE`.
- Completely empty lines after the header are ignored.

Example header (your file may differ):

`Symbol`, `BaseSymbol`, `Quantity`, `StrikeRange`, `StrikeStep`, `StartTime`, `Target`, `StopLoss`, `ExpieryDate`, `ExpType`, `TradeType`, `StartTime`, `StopTime`, `TRADINGENABLED`

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
├── app.py                 # Flask app and CSV read/write
├── requirements.txt       # Python dependencies
├── TradeSettings.csv      # Editable settings (committed or gitignored per your choice)
├── templates/
│   └── index.html         # Dashboard shell
└── static/
    ├── css/style.css      # Dark theme + layout
    └── js/app.js          # API client and UI behavior
```

## License

Add a license file if you plan to distribute the project; none is included by default.
