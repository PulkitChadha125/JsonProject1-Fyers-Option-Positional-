"""Thorough tests for TIMERAGE1/2/3 enable/disable feature."""

from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import time
from pathlib import Path
from unittest import mock

import app as app_module
import strategy_runtime


class TimerangeEnabledMigrationTests(unittest.TestCase):
    def test_migrates_missing_enabled_columns_after_each_timerage(self):
        headers = [
            "Symbol",
            "BaseSymbol",
            "Quantity",
            "StrikeStep",
            "TimeRage1",
            "TimeRage2",
            "TimeRage3",
            "SqaureoffTime",
            "Target",
            "StopLoss",
            "ExpieryDate",
            "ExpType",
            "TRADINGENABLED",
        ]
        row = [
            "NSE:NIFTY26MAYFUT",
            "NIFTY",
            "65",
            "50",
            "09:45",
            "11:30",
            "13:30",
            "15:10",
            "1",
            "",
            "28-05-2026",
            "MONTHLY",
            "TRUE",
        ]
        new_h, new_r, changed = app_module._ensure_timerange_enabled_columns(headers, [row])
        self.assertTrue(changed)
        norms = [app_module._norm_header(h) for h in new_h]
        self.assertIn("TIMERAGE1ENABLED", norms)
        self.assertIn("TIMERAGE2ENABLED", norms)
        self.assertIn("TIMERAGE3ENABLED", norms)
        # Enabled columns sit immediately after each TimeRageN.
        self.assertEqual(new_h[norms.index("TIMERAGE1") + 1], "TimeRage1Enabled")
        self.assertEqual(new_h[norms.index("TIMERAGE2") + 1], "TimeRage2Enabled")
        self.assertEqual(new_h[norms.index("TIMERAGE3") + 1], "TimeRage3Enabled")
        self.assertEqual(len(new_r[0]), len(new_h))
        for n in (1, 2, 3):
            ei = norms.index(f"TIMERAGE{n}ENABLED")
            self.assertEqual(new_r[0][ei], "TRUE")

    def test_idempotent_when_enabled_columns_already_present(self):
        headers = [
            "Symbol",
            "TimeRage1",
            "TimeRage1Enabled",
            "TimeRage2",
            "TimeRage2Enabled",
            "TimeRage3",
            "TimeRage3Enabled",
            "TRADINGENABLED",
        ]
        row = ["NSE:X", "09:45", "TRUE", "11:30", "FALSE", "13:30", "TRUE", "TRUE"]
        new_h, new_r, changed = app_module._ensure_timerange_enabled_columns(headers, [row])
        self.assertFalse(changed)
        self.assertEqual(new_h, headers)
        self.assertEqual(new_r[0], row)

    def test_normalizes_yes_no_and_blank_enable_values(self):
        headers = [
            "TimeRage1",
            "TimeRage1Enabled",
            "TimeRage2",
            "TimeRage2Enabled",
            "TimeRage3",
            "TimeRage3Enabled",
        ]
        row = ["09:45", "yes", "11:30", "0", "13:30", ""]
        new_h, new_r, changed = app_module._ensure_timerange_enabled_columns(headers, [row])
        self.assertTrue(changed)
        self.assertEqual(new_r[0][1], "TRUE")
        self.assertEqual(new_r[0][3], "FALSE")
        self.assertEqual(new_r[0][5], "TRUE")  # blank => TRUE

    def test_default_empty_row_sets_enable_true(self):
        headers = [
            "Symbol",
            "TimeRage1",
            "TimeRage1Enabled",
            "TimeRage2",
            "TimeRage2Enabled",
            "TimeRage3",
            "TimeRage3Enabled",
            "TRADINGENABLED",
        ]
        row = app_module._default_empty_row(headers)
        self.assertEqual(row[2], "TRUE")
        self.assertEqual(row[4], "TRUE")
        self.assertEqual(row[6], "TRUE")
        self.assertEqual(row[7], "FALSE")


class StrategyWindowFilterTests(unittest.TestCase):
    def _write_csv(self, path: Path, headers: list[str], rows: list[list[str]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            w.writerows(rows)

    def _load_from(self, headers: list[str], rows: list[list[str]]):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "TradeSettings.csv"
            self._write_csv(p, headers, rows)
            with mock.patch.object(strategy_runtime, "TRADE_CSV_PATH", p):
                return strategy_runtime._load_active_settings()

    def _base_headers(self) -> list[str]:
        return [
            "Symbol",
            "BaseSymbol",
            "Quantity",
            "StrikeStep",
            "TimeRage1",
            "TimeRage1Enabled",
            "TimeRage2",
            "TimeRage2Enabled",
            "TimeRage3",
            "TimeRage3Enabled",
            "SqaureoffTime",
            "Target",
            "StopLoss",
            "ExpieryDate",
            "ExpType",
            "TRADINGENABLED",
        ]

    def _base_row(
        self,
        e1: str = "TRUE",
        e2: str = "TRUE",
        e3: str = "TRUE",
        t1: str = "09:45",
        t2: str = "11:30",
        t3: str = "13:30",
        trading: str = "TRUE",
    ) -> list[str]:
        return [
            "NSE:NIFTY26MAYFUT",
            "NIFTY",
            "65",
            "50",
            t1,
            e1,
            t2,
            e2,
            t3,
            e3,
            "15:10",
            "1",
            "",
            "28-05-2026",
            "MONTHLY",
            trading,
        ]

    def test_all_enabled_loads_three_windows(self):
        settings, err = self._load_from(self._base_headers(), [self._base_row()])
        self.assertEqual(err, "")
        self.assertEqual(len(settings), 1)
        self.assertEqual(
            settings[0]["time_ranges"],
            [time(9, 45), time(11, 30), time(13, 30)],
        )

    def test_disable_middle_window_keeps_first_and_third(self):
        settings, err = self._load_from(
            self._base_headers(),
            [self._base_row(e1="TRUE", e2="FALSE", e3="TRUE")],
        )
        self.assertEqual(err, "")
        self.assertEqual(len(settings), 1)
        self.assertEqual(settings[0]["time_ranges"], [time(9, 45), time(13, 30)])

    def test_only_first_enabled(self):
        settings, err = self._load_from(
            self._base_headers(),
            [self._base_row(e1="TRUE", e2="FALSE", e3="FALSE")],
        )
        self.assertEqual(err, "")
        self.assertEqual(settings[0]["time_ranges"], [time(9, 45)])

    def test_only_third_enabled(self):
        settings, err = self._load_from(
            self._base_headers(),
            [self._base_row(e1="FALSE", e2="FALSE", e3="TRUE")],
        )
        self.assertEqual(err, "")
        self.assertEqual(settings[0]["time_ranges"], [time(13, 30)])

    def test_all_disabled_skips_row(self):
        settings, err = self._load_from(
            self._base_headers(),
            [self._base_row(e1="FALSE", e2="FALSE", e3="FALSE")],
        )
        self.assertEqual(settings, [])
        self.assertIn("No active settings", err)

    def test_enabled_but_empty_time_is_skipped(self):
        settings, err = self._load_from(
            self._base_headers(),
            [self._base_row(e1="TRUE", e2="TRUE", e3="FALSE", t1="09:45", t2="")],
        )
        self.assertEqual(err, "")
        self.assertEqual(settings[0]["time_ranges"], [time(9, 45)])

    def test_missing_enabled_columns_defaults_all_on(self):
        headers = [
            "Symbol",
            "BaseSymbol",
            "Quantity",
            "StrikeStep",
            "TimeRage1",
            "TimeRage2",
            "TimeRage3",
            "SqaureoffTime",
            "ExpieryDate",
            "ExpType",
            "TRADINGENABLED",
        ]
        row = [
            "NSE:NIFTY26MAYFUT",
            "NIFTY",
            "65",
            "50",
            "09:45",
            "11:30",
            "13:30",
            "15:10",
            "28-05-2026",
            "MONTHLY",
            "TRUE",
        ]
        settings, err = self._load_from(headers, [row])
        self.assertEqual(err, "")
        self.assertEqual(
            settings[0]["time_ranges"],
            [time(9, 45), time(11, 30), time(13, 30)],
        )

    def test_trading_disabled_row_ignored(self):
        settings, err = self._load_from(
            self._base_headers(),
            [self._base_row(trading="FALSE")],
        )
        self.assertEqual(settings, [])
        self.assertIn("No active settings", err)

    def test_yes_on_aliases_for_enable(self):
        settings, err = self._load_from(
            self._base_headers(),
            [self._base_row(e1="YES", e2="OFF", e3="1")],
        )
        self.assertEqual(err, "")
        self.assertEqual(settings[0]["time_ranges"], [time(9, 45), time(13, 30)])


class FlaskApiTimerangeTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.csv_path = Path(self._tmpdir.name) / "TradeSettings.csv"
        headers = [
            "Symbol",
            "BaseSymbol",
            "Quantity",
            "StrikeStep",
            "TimeRage1",
            "TimeRage1Enabled",
            "TimeRage2",
            "TimeRage2Enabled",
            "TimeRage3",
            "TimeRage3Enabled",
            "SqaureoffTime",
            "Target",
            "StopLoss",
            "ExpieryDate",
            "ExpType",
            "TRADINGENABLED",
        ]
        row = [
            "NSE:NIFTY26MAYFUT",
            "NIFTY",
            "65",
            "50",
            "09:45",
            "TRUE",
            "11:30",
            "TRUE",
            "13:30",
            "TRUE",
            "15:10",
            "1",
            "",
            "28-05-2026",
            "MONTHLY",
            "TRUE",
        ]
        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            w.writerow(row)
        self._csv_patch = mock.patch.object(app_module, "CSV_PATH", self.csv_path)
        self._csv_patch.start()
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._csv_patch.stop()
        self._tmpdir.cleanup()

    def test_get_settings_includes_enabled_columns(self):
        r = self.client.get("/api/settings")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        norms = [app_module._norm_header(h) for h in data["headers"]]
        self.assertIn("TIMERAGE1ENABLED", norms)
        self.assertIn("TIMERAGE2ENABLED", norms)
        self.assertIn("TIMERAGE3ENABLED", norms)
        self.assertEqual(len(data["rows"]), 1)

    def test_put_disables_second_window_and_persists(self):
        get0 = self.client.get("/api/settings").get_json()
        headers = get0["headers"]
        row = list(get0["rows"][0])
        norms = [app_module._norm_header(h) for h in headers]
        e2 = norms.index("TIMERAGE2ENABLED")
        row[e2] = "FALSE"
        r = self.client.put(
            "/api/settings/0",
            json={"values": row},
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["row"][e2], "FALSE")

        # Reload from disk
        get1 = self.client.get("/api/settings").get_json()
        self.assertEqual(get1["rows"][0][e2], "FALSE")

        # Strategy must honor it
        with mock.patch.object(strategy_runtime, "TRADE_CSV_PATH", self.csv_path):
            settings, err = strategy_runtime._load_active_settings()
        self.assertEqual(err, "")
        self.assertEqual(settings[0]["time_ranges"], [time(9, 45), time(13, 30)])

    def test_put_normalizes_yes_to_true(self):
        get0 = self.client.get("/api/settings").get_json()
        headers = get0["headers"]
        row = list(get0["rows"][0])
        norms = [app_module._norm_header(h) for h in headers]
        e1 = norms.index("TIMERAGE1ENABLED")
        row[e1] = "yes"
        r = self.client.put("/api/settings/0", json={"values": row})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["row"][e1], "TRUE")

    def test_post_new_row_defaults_enables_true(self):
        r = self.client.post("/api/settings", json={})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        get0 = self.client.get("/api/settings").get_json()
        norms = [app_module._norm_header(h) for h in get0["headers"]]
        for n in (1, 2, 3):
            ei = norms.index(f"TIMERAGE{n}ENABLED")
            self.assertEqual(body["row"][ei], "TRUE")

    def test_migrate_on_read_from_legacy_csv(self):
        legacy = Path(self._tmpdir.name) / "legacy.csv"
        with legacy.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "Symbol",
                    "BaseSymbol",
                    "Quantity",
                    "StrikeStep",
                    "TimeRage1",
                    "TimeRage2",
                    "TimeRage3",
                    "SqaureoffTime",
                    "ExpieryDate",
                    "ExpType",
                    "TRADINGENABLED",
                ]
            )
            w.writerow(
                [
                    "NSE:NIFTY26MAYFUT",
                    "NIFTY",
                    "65",
                    "50",
                    "09:45",
                    "11:30",
                    "13:30",
                    "15:10",
                    "28-05-2026",
                    "MONTHLY",
                    "TRUE",
                ]
            )
        with mock.patch.object(app_module, "CSV_PATH", legacy):
            headers, rows = app_module._read_csv()
        norms = [app_module._norm_header(h) for h in headers]
        self.assertIn("TIMERAGE1ENABLED", norms)
        self.assertIn("TIMERAGE2ENABLED", norms)
        self.assertIn("TIMERAGE3ENABLED", norms)
        for n in (1, 2, 3):
            self.assertEqual(rows[0][norms.index(f"TIMERAGE{n}ENABLED")], "TRUE")
        # Persisted to disk
        with legacy.open(newline="", encoding="utf-8") as f:
            disk = list(csv.reader(f))
        disk_norms = [app_module._norm_header(h) for h in disk[0]]
        self.assertIn("TIMERAGE2ENABLED", disk_norms)


class JsHelperParityTests(unittest.TestCase):
    """Lightweight parity checks for JS naming helpers (reimplemented in Python)."""

    @staticmethod
    def _norm(name: str) -> str:
        return "".join(ch for ch in name.lower() if ch.isalnum())

    def test_timerage_column_detection(self):
        def is_time_rage(name: str) -> bool:
            n = self._norm(name)
            return n in {
                "timerage1",
                "timerage2",
                "timerage3",
                "timerange1",
                "timerange2",
                "timerange3",
            }

        def is_enabled(name: str) -> bool:
            n = self._norm(name)
            return n.endswith("enabled") and n.startswith(("timerage", "timerange"))

        self.assertTrue(is_time_rage("TimeRage1"))
        self.assertTrue(is_time_rage("TimeRange2"))
        self.assertFalse(is_time_rage("TimeRage1Enabled"))
        self.assertTrue(is_enabled("TimeRage2Enabled"))
        self.assertFalse(is_enabled("TRADINGENABLED"))
        self.assertFalse(is_time_rage("SqaureoffTime"))


class CurrentProjectCsvSmokeTest(unittest.TestCase):
    def test_project_tradesettings_has_enabled_columns(self):
        path = Path(__file__).resolve().parent / "TradeSettings.csv"
        self.assertTrue(path.is_file())
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        headers = rows[0]
        norms = [app_module._norm_header(h) for h in headers]
        for n in (1, 2, 3):
            self.assertIn(f"TIMERAGE{n}ENABLED", norms)
        # Strategy load against real file should succeed with current TRUE/TRUE/TRUE
        with mock.patch.object(strategy_runtime, "TRADE_CSV_PATH", path):
            settings, err = strategy_runtime._load_active_settings()
        self.assertEqual(err, "")
        self.assertGreaterEqual(len(settings), 1)
        self.assertEqual(len(settings[0]["time_ranges"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
