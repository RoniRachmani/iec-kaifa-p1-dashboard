"""Stdlib tests: python3 -m unittest discover -s tests

The fixture is a real telegram from a Kaifa MA110M with the equipment ID
masked and the CRC recomputed.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tempfile  # noqa: E402
import time  # noqa: E402

import server  # noqa: E402
from unittest import mock  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

from server import Config, Hub, Store, crc16, find_port, handle_telegram, host_allowed, in_window, make_handler, parse  # noqa: E402


def telegram(lines):
    body = b"/KFM5KAIFA-METER\r\n\r\n" + b"".join(l + b"\r\n" for l in lines) + b"!"
    return body + b"%04X" % crc16(body)


def query(st, sql):
    con = st.connect()
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()

with open(os.path.join(HERE, "fixtures", "telegram.txt"), "rb") as fh:
    TELEGRAM = fh.read().rstrip(b"\r\n")


class Crc(unittest.TestCase):
    def test_crc16_arc_check_value(self):
        # The CRC-16/ARC check value for "123456789"
        self.assertEqual(crc16(b"123456789"), 0xBB3D)

    def test_fixture_crc(self):
        self.assertEqual(int(TELEGRAM[-4:], 16), crc16(TELEGRAM[:-4]))


class Parse(unittest.TestCase):
    def test_fields(self):
        r = parse(TELEGRAM)
        self.assertIsNotNone(r)
        self.assertEqual(r["imp"], [699.801, 0.0, 2296.804])
        self.assertEqual(r["imp_total"], 2996.605)
        self.assertEqual(r["exp_total"], 0)
        self.assertEqual(r["p_in"], 380.0)
        self.assertEqual(r["v"], 240.0)
        self.assertEqual(r["a"], 1.7)
        self.assertEqual(r["tariff"], 3)
        self.assertEqual(r["meter_time"], "261114012442W")

    def test_bad_crc_rejected(self):
        self.assertIsNone(parse(TELEGRAM[:-4] + b"0000"))

    def test_corrupted_body_rejected(self):
        self.assertIsNone(parse(TELEGRAM.replace(b"240.0*V", b"241.0*V")))

    def test_garbage_crc_rejected(self):
        self.assertIsNone(parse(TELEGRAM[:-4] + b"ZZZZ"))

    def test_dutch_two_tariff_fallback(self):
        body = (b"/XMX5TEST\r\n\r\n1-0:1.8.1(000100.000*kWh)\r\n1-0:1.8.2(000050.500*kWh)\r\n"
                b"1-0:1.7.0(01.234*kW)\r\n!")
        r = parse(body + b"%04X" % crc16(body))
        self.assertEqual(r["imp"], [100.0, 50.5, None])
        self.assertEqual(r["imp_total"], 150.5)
        self.assertEqual(r["p_in"], 1234.0)

    def test_single_phase_has_one_phase(self):
        ph = parse(TELEGRAM)["phases"]
        self.assertEqual(ph, [{"l": 1, "v": 240.0, "a": 1.7, "p_in": None, "p_out": None}])

    def test_three_phase(self):
        # Kaifa MA309M-style: same tariff codes, plus L2/L3 voltage, current and power
        body = (b"/KFM5KAIFA-METER\r\n\r\n1-3:0.2.8(50)\r\n0-0:96.14.1(01)\r\n"
                b"1-0:1.8.11(001000.000*kWh)\r\n1-0:1.8.12(000000.000*kWh)\r\n1-0:1.8.13(002000.000*kWh)\r\n"
                b"1-0:1.7.0(03.450*kW)\r\n1-0:2.7.0(00.000*kW)\r\n"
                b"1-0:32.7.0(231.0*V)\r\n1-0:52.7.0(229.0*V)\r\n1-0:72.7.0(230.0*V)\r\n"
                b"1-0:31.7.0(002.0*A)\r\n1-0:51.7.0(010.5*A)\r\n1-0:71.7.0(001.0*A)\r\n"
                b"1-0:21.7.0(00.460*kW)\r\n1-0:41.7.0(02.400*kW)\r\n1-0:61.7.0(00.590*kW)\r\n!")
        r = parse(body + b"%04X" % crc16(body))
        self.assertEqual(r["imp_total"], 3000.0)
        self.assertEqual(r["p_in"], 3450.0)
        self.assertEqual([p["l"] for p in r["phases"]], [1, 2, 3])
        self.assertEqual([p["v"] for p in r["phases"]], [231.0, 229.0, 230.0])
        self.assertEqual([p["a"] for p in r["phases"]], [2.0, 10.5, 1.0])
        self.assertEqual([p["p_in"] for p in r["phases"]], [460.0, 2400.0, 590.0])
        self.assertEqual(r["v"], 231.0)  # L1 still in the flat fields
        self.assertEqual(r["tariff"], 1)

    def test_standard_tariff_indicator(self):
        body = b"/XMX5TEST\r\n\r\n1-0:1.8.1(000001.000*kWh)\r\n0-0:96.14.0(0002)\r\n!"
        self.assertEqual(parse(body + b"%04X" % crc16(body))["tariff"], 2)


class PortDetection(unittest.TestCase):
    def fake_glob(self, existing):
        import fnmatch
        return lambda pattern: [p for p in existing if fnmatch.fnmatch(p, pattern)]

    def test_macos(self):
        with mock.patch.object(server.glob, "glob", self.fake_glob(["/dev/cu.usbserial-AB12"])):
            self.assertEqual(find_port(), "/dev/cu.usbserial-AB12")

    def test_linux_prefers_stable_by_id_name(self):
        devs = ["/dev/ttyUSB0", "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AB12-if00-port0"]
        with mock.patch.object(server.glob, "glob", self.fake_glob(devs)):
            self.assertEqual(find_port(), devs[1])

    def test_linux_plain_ttyusb(self):
        with mock.patch.object(server.glob, "glob", self.fake_glob(["/dev/ttyUSB1", "/dev/ttyUSB0"])):
            self.assertEqual(find_port(), "/dev/ttyUSB0")

    def test_nothing_plugged_in(self):
        with mock.patch.object(server.glob, "glob", self.fake_glob([])):
            self.assertIsNone(find_port())


class Windows(unittest.TestCase):
    NIGHT = {"days": [0, 1, 2, 3, 4], "from": 23, "to": 7}   # Sun-Thu 23:00-07:00
    DAY = {"days": [0, 1, 2, 3, 4], "from": 7, "to": 17}

    def test_night_belongs_to_start_day(self):
        self.assertTrue(in_window(4, 23.5, self.NIGHT))   # Thu 23:30
        self.assertTrue(in_window(5, 3, self.NIGHT))      # Fri 03:00 (Thursday night)
        self.assertFalse(in_window(5, 23.5, self.NIGHT))  # Fri 23:30
        self.assertFalse(in_window(0, 3, self.NIGHT))     # Sun 03:00 (Saturday night)

    def test_day(self):
        self.assertTrue(in_window(0, 7, self.DAY))
        self.assertFalse(in_window(0, 17, self.DAY))
        self.assertFalse(in_window(6, 10, self.DAY))      # Saturday

    def test_fixed_plan(self):
        self.assertTrue(in_window(6, 3, {"discount": 6.5}))


class RecentBackfill(unittest.TestCase):
    def test_store_recent_returns_flagged_averages(self):
        with tempfile.TemporaryDirectory() as d:
            st = Store(os.path.join(d, "p1.sqlite"))
            con = st.connect()
            now = time.time()
            for k in range(6):  # one row per 10 s, ending now
                ts = now - 50 + k * 10
                con.execute("INSERT INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (ts, 200 + k, 210, 0, 230, 1, 1, 0, 1, 0, 0, 0, 3))
            con.commit(); con.close()
            pts = st.recent(now - 900, now - 15)
            st.close()
            self.assertEqual(len(pts), 4)                  # rows before the cut-off only
            self.assertEqual([p[2] for p in pts], [1] * 4)  # flagged as averages
            self.assertAlmostEqual(pts[0][0], now - 55, delta=0.2)  # centred on the 10 s window
            self.assertEqual(pts[0][1], 200)


class ReaderRobustness(unittest.TestCase):
    def test_telegram_without_power_is_logged_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            hub, st = Hub(), Store(os.path.join(d, "p1.sqlite"))
            handle_telegram(telegram([b"1-0:1.8.11(000001.000*kWh)"]), hub, st)
            self.assertEqual((hub.ok, hub.errors), (1, 0))
            row = query(st, "SELECT p_in, p_max, i1 FROM readings")[0]
            st.close()
            self.assertEqual(row, (None, None, 1.0))

    def test_unexpected_error_is_counted_and_reading_continues(self):
        class Broken:
            def add(self, rec):
                raise RuntimeError("boom")
        hub = Hub()
        handle_telegram(TELEGRAM, hub, Broken())
        handle_telegram(TELEGRAM, hub, Broken())
        self.assertEqual((hub.ok, hub.errors), (2, 2))
        self.assertIn("RuntimeError: boom", hub.last_error[1])
        self.assertIsNotNone(hub.latest)  # the live view still got the reading

    def test_bad_crc_counts_as_bad(self):
        hub = Hub()
        handle_telegram(TELEGRAM[:-4] + b"0000", hub, None)
        self.assertEqual((hub.ok, hub.bad, hub.errors), (0, 1, 0))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(os.path.join(cls.tmp.name, "p1.sqlite"))
        cls.hub = Hub()
        cfg = Config(os.path.join(cls.tmp.name, "config.json"))
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.hub, cls.store, cfg))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def status(self, path, **kw):
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, **kw), timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_bad_parameters_return_400(self):
        for path in ("/api/history?seconds=abc", "/api/hourly?date=2026-13-45", "/api/plans?days=x"):
            self.assertEqual(self.status(path)[0], 400, path)

    def post_config(self, body=b'{"currency": "\u20aa", "prices": [0.6, 0.6, 0.6]}', **headers):
        return self.status("/api/config", data=body, method="POST", headers=headers)[0]

    def test_post_needs_json_content_type(self):
        self.assertEqual(self.post_config(**{"Content-Type": "text/plain"}), 415)

    def test_post_from_another_origin_is_refused(self):
        self.assertEqual(self.post_config(**{"Content-Type": "application/json",
                                             "Origin": "https://evil.example"}), 403)
        self.assertEqual(self.post_config(**{"Content-Type": "application/json", "Origin": "null"}), 403)

    def test_post_same_origin_and_no_origin_work(self):
        host = self.base.split("//")[1]
        self.assertEqual(self.post_config(**{"Content-Type": "application/json", "Origin": "http://" + host}), 200)
        self.assertEqual(self.post_config(**{"Content-Type": "application/json"}), 200)  # curl, scripts

    def test_foreign_host_header_is_refused(self):
        self.assertEqual(self.status("/api/meta", headers={"Host": "rebind.evil.example:8765"})[0], 403)
        self.assertEqual(self.status("/api/meta", headers={"Host": "localhost:8765"})[0], 200)

    def test_meta_reports_age_and_errors(self):
        code, body = self.status("/api/meta")
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertIn("age", d)
        self.assertEqual(d["errors"], 0)


def rec(ts, regs, p_in=1000.0, tariff=3):
    return {"ts": ts, "p_in": p_in, "p_out": 0.0, "v": 230.0, "a": 4.3, "tariff": tariff,
            "imp": list(regs), "exp": [0.0, 0.0, 0.0]}


class HostAllowed(unittest.TestCase):
    def test_rules(self):
        me = server.socket.gethostname().split(".")[0]
        for h in ("127.0.0.1:8765", "[::1]:8765", "192.168.1.20:8765", "localhost:8765", "LOCALHOST",
                  f"{me}:8765", f"{me}.local:8765"):
            self.assertTrue(host_allowed(h), h)
        for h in (None, "", "evil.example", "evil.example:8765", "localhost.evil.example"):
            self.assertFalse(host_allowed(h), h)
        self.assertTrue(host_allowed("pi-meter:8765", ["pi-meter"]))


class Summary(unittest.TestCase):
    """The hourly summary table that stats, plans and the hourly chart read."""

    def setUp(self):
        self.old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Jerusalem"  # DST dates below are Israel's
        time.tzset()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "p1.sqlite")

    def tearDown(self):
        if self.old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.old_tz
        time.tzset()
        self.tmp.cleanup()

    def raw_day(self, day, kw=1.0, step=10):
        """Raw rows for one local day at a constant load, counted on T3."""
        from datetime import datetime, time as dtime, timedelta
        start = datetime.combine(day, dtime()).timestamp()
        end = datetime.combine(day + timedelta(days=1), dtime()).timestamp()
        con = Store(self.path).connect()
        e, ts = 100.0, start
        while ts < end:
            con.execute("INSERT INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, kw * 1000, kw * 1000, 0, 230, 4, 0.0, 0.0, e, 0, 0, 0, 3))
            ts += step
            e += kw * step / 3600
        con.commit()
        con.close()
        st = Store(self.path)  # a fresh Store rebuilds the summary for existing data
        return st

    def test_autumn_day_has_25_hours(self):
        from datetime import date
        h = self.raw_day(date(2026, 10, 25)).hourly(date(2026, 10, 25))["hours"]
        self.assertAlmostEqual(h[1][2], 2.0, places=2)   # 01:00-02:00 happens twice
        self.assertAlmostEqual(h[0][2], 1.0, places=2)
        self.assertAlmostEqual(h[23][2], 1.0, places=2)
        self.assertAlmostEqual(sum(x[2] for x in h if x), 25.0, places=2)

    def test_spring_day_has_23_hours(self):
        from datetime import date
        h = self.raw_day(date(2026, 3, 27)).hourly(date(2026, 3, 27))["hours"]
        self.assertIsNone(h[2])                          # 02:00-03:00 doesn't exist
        self.assertAlmostEqual(h[3][2], 1.0, places=2)
        self.assertAlmostEqual(sum(x[2] for x in h if x), 23.0, places=2)

    def test_plans_on_the_25_hour_day(self):
        from datetime import date, datetime, time as dtime
        day = date(2026, 10, 25)                         # Sunday; clocks go back at 02:00
        st = self.raw_day(day)
        end = datetime.combine(date(2026, 10, 26), dtime()).timestamp()
        with mock.patch.object(server.time, "time", return_value=end):
            r = st.plans([0.5, 0.5, 0.5], 1.05)
        st.close()
        share = {(p["supplier"].split()[0], p["name"]): p["share"] for p in r["plans"]}
        self.assertAlmostEqual(r["kwh"], 25.0, places=2)                       # 25 real hours
        self.assertAlmostEqual(share[("Super", "Fixed")], 1.0, places=6)
        self.assertAlmostEqual(share[("Super", "Day")], 10 / 25, places=3)     # 07-17
        self.assertAlmostEqual(share[("Cellcom", "Afternoon / evening")], 6 / 25, places=3)  # 14-20
        # Night windows start Sun-Thu at 23:00. Sunday 00-07 belongs to Saturday night (no discount),
        # including the repeated 01:00 hour, so only Sunday 23:00-24:00 counts.
        self.assertAlmostEqual(share[("Super", "Night Plus")], 1 / 25, places=3)

    def test_missing_counter_is_skipped_not_a_spike(self):
        st = Store(self.path)
        t0 = 1_800_000_000
        st.add(rec(t0, [1.0, 0.0, 2296.0]))
        st.add(rec(t0 + 10, [1.0, 0.0, None]))          # one row lost its T3 value
        st.add(rec(t0 + 20, [1.0, 0.0, 2296.01]))
        total = query(st, "SELECT SUM(d1 + d2 + d3) FROM hours")[0][0]
        st.close()
        self.assertLess(total, 0.02)

    def test_implausible_jump_and_counter_reset_are_skipped(self):
        st = Store(self.path)
        t0 = 1_800_000_000
        st.add(rec(t0, [0.0, 0.0, 100.0]))
        st.add(rec(t0 + 10, [0.0, 0.0, 150.0]))         # 50 kWh in 10 s = 18 MW
        st.add(rec(t0 + 20, [0.0, 0.0, 10.0]))          # counter went backwards
        st.add(rec(t0 + 30, [0.0, 0.0, 10.003]))        # normal: about 1 kW
        total = query(st, "SELECT SUM(d3) FROM hours")[0][0]
        st.close()
        self.assertAlmostEqual(total, 0.003, places=6)

    def test_live_matches_rebuild_and_repeats_are_ignored(self):
        st = Store(self.path)
        t0 = 1_800_000_000
        for k in range(400):                             # a bit over an hour, tariff switch midway
            st.add(rec(t0 + k * 10, [k * 0.001, 0.0, 5.0], p_in=900 + k, tariff=1 if k >= 200 else 3))
        st.add(rec(t0 + 50, [0.05, 0.0, 5.0]))           # an old timestamp arriving late
        q = "SELECT hour_ts, round(d1, 6), round(secs, 3), round(t1, 3), round(t3, 3), n, p_max FROM hours ORDER BY 1"
        live = query(st, q)
        st.rebuild_summary()
        self.assertEqual(query(st, q), live)
        stats = st.stats()
        self.assertEqual(stats["rows"], 400)
        self.assertEqual([(c["from"], c["to"]) for c in stats["tariff_changes"]], [(3, 1)])
        self.assertAlmostEqual(stats["tariff_secs"]["3"] + stats["tariff_secs"]["1"], 3990, places=3)
        st.close()

    def test_plans_use_whole_hour_windows(self):
        from datetime import datetime
        st = Store(self.path)
        # Sunday 1 Nov 2026, 22:00-00:00 local at 1 kW: 22-23 is outside the night window, 23-24 inside
        t0 = datetime(2026, 11, 1, 22, 0).timestamp()
        for k in range(721):
            st.add(rec(t0 + k * 10, [0.0, 0.0, k * 10 / 3600]))
        with mock.patch.object(server.time, "time", return_value=t0 + 7300):
            r = st.plans([0.5, 0.5, 0.5], 28)
        st.close()
        night = next(p for p in r["plans"] if p["supplier"].startswith("Super") and p["name"] == "Night Plus")
        fixed = next(p for p in r["plans"] if p["supplier"].startswith("Super") and p["name"] == "Fixed")
        self.assertAlmostEqual(r["kwh"], 2.0, places=2)
        self.assertAlmostEqual(night["share"], 0.5, places=2)
        self.assertAlmostEqual(fixed["share"], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
