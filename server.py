#!/usr/bin/env python3
"""Live dashboard for a P1 (DSMR 5) smart meter on a USB serial cable.

Stdlib only. Reads telegrams at 115200 8N1, verifies CRC16, keeps the last
15 minutes in memory, logs a 10-second average to SQLite, and serves a
dashboard at http://127.0.0.1:8765

    python3 server.py                     # auto-detect (macOS /dev/cu.usbserial*, Linux /dev/ttyUSB*)
    python3 server.py --port /dev/cu.usbserial-XXXXXXXX
    python3 server.py --host 0.0.0.0      # also reachable from your phone on the LAN
"""
import argparse
import glob
import ipaddress
import json
import math
import os
import re
import select
import socket
import sqlite3
import termios
import threading
import time
from collections import deque
from datetime import date, datetime, time as dtime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
LINE = re.compile(r"^(\d+-\d+:\d+\.\d+\.\d+)((?:\([^)]*\))+)\s*$")
VALS = re.compile(r"\(([^)]*)\)")
LOG_EVERY = 10  # seconds between SQLite rows
RECENT_S = 900  # seconds of 1-second points kept in memory
MAX_GAP = 120   # longer gaps between rows are left out of plan comparisons


def in_window(sunday_day, hour, plan):
    """Is this moment inside a supplier plan's discount window? No window = all hours.
    A window that crosses midnight (23-07) belongs to the night it starts on."""
    if "from" not in plan:
        return True
    a, b, days = plan["from"], plan["to"], plan["days"]
    if a < b:
        return sunday_day in days and a <= hour < b
    return (hour >= a and sunday_day in days) or (hour < b and (sunday_day - 1) % 7 in days)


# ---------------------------------------------------------------- parsing
# (voltage, current, power imported, power exported) per phase
PHASE_CODES = [
    ("1-0:32.7.0", "1-0:31.7.0", "1-0:21.7.0", "1-0:22.7.0"),
    ("1-0:52.7.0", "1-0:51.7.0", "1-0:41.7.0", "1-0:42.7.0"),
    ("1-0:72.7.0", "1-0:71.7.0", "1-0:61.7.0", "1-0:62.7.0"),
]


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def meter_id(raw):
    """The equipment ID (0-0:96.1.1) as text. Kaifa sends plain ASCII (K06...); Dutch meters
    send the same text hex-encoded (4530...), which is decoded here."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if len(raw) >= 8 and len(raw) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in raw):
        try:
            text = bytes.fromhex(raw).decode("ascii")
            if text.isprintable() and text.strip():
                return text.strip()
        except (ValueError, UnicodeDecodeError):
            pass
    return raw


def parse(tele: bytes):
    """tele = b'/...!' + 4 hex CRC chars. Returns a dict or None if invalid."""
    body, crc = tele[:-4], tele[-4:]
    try:
        if int(crc, 16) != crc16(body):
            return None
    except ValueError:
        return None
    fields = {}
    for line in body.decode("ascii", "replace").splitlines():
        m = LINE.match(line.strip())
        if m:
            fields[m.group(1)] = VALS.findall(m.group(2))

    def f(code):
        try:
            return float(fields[code][0].split("*")[0])
        except (KeyError, IndexError, ValueError):
            return None

    # This meter uses three tariff registers (x.8.11-13); Dutch meters use x.8.1-2.
    imp = [f("1-0:1.8.11"), f("1-0:1.8.12"), f("1-0:1.8.13")]
    exp = [f("1-0:2.8.11"), f("1-0:2.8.12"), f("1-0:2.8.13")]
    if all(v is None for v in imp):
        imp = [f("1-0:1.8.1"), f("1-0:1.8.2"), None]
        exp = [f("1-0:2.8.1"), f("1-0:2.8.2"), None]
    p_in, p_out = f("1-0:1.7.0"), f("1-0:2.7.0")
    tariff = f("0-0:96.14.1")
    if tariff is None:
        tariff = f("0-0:96.14.0")  # standard DSMR code
    # Per phase: L1 always on single-phase meters; L2/L3 only on 3-phase (e.g. Kaifa MA309M).
    phases = []
    for n, (cv, ca, cpi, cpo) in enumerate(PHASE_CODES, 1):
        v, a, pi, po = f(cv), f(ca), f(cpi), f(cpo)
        if v is None and a is None:
            continue
        phases.append({"l": n, "v": v, "a": a,
                       "p_in": None if pi is None else round(pi * 1000, 1),
                       "p_out": None if po is None else round(po * 1000, 1)})
    return {
        "ts": time.time(),
        "meter_time": (fields.get("0-0:1.0.0") or [None])[0],
        "meter_id": meter_id((fields.get("0-0:96.1.1") or [None])[0]),
        "p_in": None if p_in is None else round(p_in * 1000, 1),
        "p_out": None if p_out is None else round(p_out * 1000, 1),
        "v": f("1-0:32.7.0"),   # L1, kept for the logger and single-phase display
        "a": f("1-0:31.7.0"),
        "phases": phases,
        "tariff": None if tariff is None else int(tariff),
        "imp": imp,
        "exp": exp,
        "imp_total": round(sum(v or 0 for v in imp), 3),
        "exp_total": round(sum(v or 0 for v in exp), 3),
    }


# ---------------------------------------------------------------- live hub
class Hub:
    def __init__(self):
        self.cv = threading.Condition()
        self.seq = 0
        self.latest = None
        self.recent = deque(maxlen=RECENT_S)
        self.raw = None          # last valid telegram text
        self.raw_ts = None
        self.ok = 0              # valid telegrams since start
        self.bad = 0             # CRC failures since start
        self.device = None
        self.started = time.time()
        self.errors = 0          # unexpected errors while handling a telegram
        self.last_error = None   # (ts, message) of the latest one

    def publish(self, rec):
        with self.cv:
            self.seq += 1
            self.latest = rec
            self.recent.append((round(rec["ts"], 1), rec["p_in"]))
            self.cv.notify_all()

    def wait(self, seq, timeout):
        with self.cv:
            self.cv.wait_for(lambda: self.seq != seq, timeout)
            return (self.latest if self.seq != seq else None), self.seq


# ---------------------------------------------------------------- storage
SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
  ts REAL PRIMARY KEY, p_in REAL, p_max REAL, p_out REAL, v REAL, a REAL,
  i1 REAL, i2 REAL, i3 REAL, e1 REAL, e2 REAL, e3 REAL, tariff INTEGER
);
-- One row per local clock hour, kept up to date as readings arrive, so the
-- dashboard never scans the raw table (about 3 million rows a year).
CREATE TABLE IF NOT EXISTS hours (
  hour_ts REAL PRIMARY KEY,           -- start of the local hour (epoch); DST-safe
  day TEXT, hour INTEGER, dow INTEGER, -- local date, local hour 0-23, 0 = Sunday
  d1 REAL DEFAULT 0, d2 REAL DEFAULT 0, d3 REAL DEFAULT 0,  -- kWh per import counter
  secs REAL DEFAULT 0,                -- seconds covered by valid intervals
  t1 REAL DEFAULT 0, t2 REAL DEFAULT 0, t3 REAL DEFAULT 0,  -- seconds on each tariff
  n INTEGER DEFAULT 0,                -- raw rows logged in this hour
  p_max REAL, p_max_ts REAL           -- highest 10-second peak and when
);
CREATE INDEX IF NOT EXISTS hours_day ON hours(day);
CREATE TABLE IF NOT EXISTS tariff_changes (ts REAL PRIMARY KEY, prev INTEGER, tariff INTEGER);
-- Small settings, such as meter_id: the equipment ID this log belongs to.
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

UPSERT_HOUR = """
INSERT INTO hours (hour_ts, day, hour, dow, d1, d2, d3, secs, t1, t2, t3, n, p_max, p_max_ts)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(hour_ts) DO UPDATE SET
  d1 = d1 + excluded.d1, d2 = d2 + excluded.d2, d3 = d3 + excluded.d3,
  secs = secs + excluded.secs, t1 = t1 + excluded.t1, t2 = t2 + excluded.t2, t3 = t3 + excluded.t3,
  n = n + excluded.n,
  p_max_ts = CASE WHEN excluded.p_max IS NOT NULL AND (p_max IS NULL OR excluded.p_max > p_max)
                  THEN excluded.p_max_ts ELSE p_max_ts END,
  p_max = CASE WHEN excluded.p_max IS NOT NULL AND (p_max IS NULL OR excluded.p_max > p_max)
               THEN excluded.p_max ELSE p_max END
"""
MAX_KW = 100  # an interval implying more than this is a glitch, not usage
# A log from before meter IDs were recorded is claimed by the first meter whose counters carry
# on from its last row: none lower, and no more than this average load across the gap.
ADOPT_KW = 25


def local_hour(ts):
    """(hour_ts, 'YYYY-MM-DD', hour, dow with 0 = Sunday) for the local hour containing ts.
    Uses the fold flag, so the repeated hour when clocks go back gets its own hour_ts."""
    lt = datetime.fromtimestamp(ts)
    start = lt.replace(minute=0, second=0, microsecond=0)
    return start.timestamp(), lt.date().isoformat(), lt.hour, (lt.weekday() + 1) % 7


def interval(prev, cur):
    """Energy between two logged rows (ts, [i1, i2, i3], tariff), or None when it can't be
    trusted: a gap over MAX_GAP, a missing counter, a counter going backwards, or a jump
    implying more than MAX_KW."""
    dt = cur[0] - prev[0]
    if not 0 < dt <= MAX_GAP:
        return None
    if any(v is None for v in prev[1]) or any(v is None for v in cur[1]):
        return None
    d = [c - p for c, p in zip(cur[1], prev[1])]
    if min(d) < 0 or sum(d) / (dt / 3600) > MAX_KW:
        return None
    return (cur[0] + prev[0]) / 2, dt, d


class Store:
    def __init__(self, path, adopt=False):
        """adopt=True: give this log to the next meter seen, even one that doesn't match."""
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        con = self.connect()
        con.executescript(SCHEMA)
        empty = con.execute("SELECT 1 FROM hours LIMIT 1").fetchone() is None
        has_rows = con.execute("SELECT 1 FROM readings LIMIT 1").fetchone() is not None
        row = con.execute("SELECT value FROM meta WHERE key = 'meter_id'").fetchone()
        con.close()
        self.meter_id = row[0] if row else None
        self.adopt = adopt
        self.foreign = None    # ID of a connected meter this log doesn't belong to
        self._warned = set()
        if empty and has_rows:
            print("building the hourly summary from the log (one-time)…", flush=True)
            self.rebuild_summary()
        self.wcon = None
        self.window = []  # p_in samples since last row
        self.prev = self._last_row()

    def _last_row(self):
        con = self.connect()
        row = con.execute("SELECT ts, i1, i2, i3, tariff FROM readings ORDER BY ts DESC LIMIT 1").fetchone()
        con.close()
        return (row[0], list(row[1:4]), row[4]) if row else None

    def _accumulate(self, con, prev, ts, regs, tariff, p_max, lo=-math.inf, hi=math.inf):
        """Fold one logged row into the hourly summary and tariff-change log.
        Only hours starting in [lo, hi) are written (used by a ranged rebuild)."""
        hts, day, hour, dow = local_hour(ts)
        if lo <= hts < hi:
            con.execute(UPSERT_HOUR, (hts, day, hour, dow, 0, 0, 0, 0, 0, 0, 0, 1, p_max, ts))
        if prev is None:
            return
        iv = interval(prev, (ts, regs, tariff))
        if iv:
            mid, dt, d = iv
            hts, day, hour, dow = local_hour(mid)
            if lo <= hts < hi:
                t = [dt if prev[2] == k else 0 for k in (1, 2, 3)]
                con.execute(UPSERT_HOUR, (hts, day, hour, dow, *d, dt, *t, 0, None, None))
        if prev[2] is not None and tariff is not None and prev[2] != tariff and lo <= ts < hi:
            con.execute("INSERT OR IGNORE INTO tariff_changes VALUES (?,?,?)", (ts, prev[2], tariff))

    def rebuild_summary(self, since=None, until=None):
        """Recompute hours and tariff_changes from the raw readings, for everything or for the
        local hours covering [since, until]. Call it after writing readings out of order (e.g. an
        ESP32 backfill): Store.add only folds in readings newer than the last one.
        Streams the rows, so memory stays flat on a large log."""
        # Widen by one MAX_GAP each side: the interval joining the range to its neighbour can
        # have its midpoint in the hour before (or after) the range.
        lo = -math.inf if since is None else local_hour(since - MAX_GAP)[0]
        hi = math.inf if until is None else local_hour(until + MAX_GAP)[0] + 3600  # local hours are 3600 s
        con = self.connect()
        con.execute("DELETE FROM hours WHERE hour_ts >= ? AND hour_ts < ?", (lo, hi))
        con.execute("DELETE FROM tariff_changes WHERE ts >= ? AND ts < ?", (lo, hi))
        # One row either side of the range supplies the neighbouring intervals.
        before = con.execute("SELECT ts, i1, i2, i3, tariff FROM readings WHERE ts < ? "
                             "ORDER BY ts DESC LIMIT 1", (lo,)).fetchone() if since is not None else None
        prev = (before[0], list(before[1:4]), before[4]) if before else None
        cur = con.cursor()
        cur.execute("SELECT ts, p_max, i1, i2, i3, tariff FROM readings WHERE ts >= ? AND ts < ? "
                    "ORDER BY ts", (lo, hi + MAX_GAP))
        while True:
            batch = cur.fetchmany(5000)
            if not batch:
                break
            for ts, p_max, i1, i2, i3, tariff in batch:
                self._accumulate(con, prev, ts, [i1, i2, i3], tariff, p_max, lo, hi)
                prev = (ts, [i1, i2, i3], tariff)
        con.commit()
        con.close()

    def connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _claim(self, mid):
        con = self.connect()
        con.execute("INSERT OR REPLACE INTO meta VALUES ('meter_id', ?)", (mid,))
        con.commit()
        con.close()
        self.meter_id, self.adopt = mid, False
        print(f"log {self.path} belongs to meter {mid}", flush=True)

    def _continues(self, r):
        """Do this reading's counters carry on from the last logged row?"""
        if self.prev is None:
            return True
        last, now = self.prev[1], r["imp"]
        if any(v is None for v in last) or any(v is None for v in now):
            return False
        d = [b - a for a, b in zip(last, now)]
        hours = max(r["ts"] - self.prev[0], 0) / 3600
        return min(d) >= 0 and sum(d) <= ADOPT_KW * hours + 0.01

    def check_meter(self, r):
        """Should this reading go into this log? A log belongs to one meter, so a different
        meter's counters never get mixed into its history. Called from the reader thread."""
        mid = r.get("meter_id")
        if mid is None or mid == self.meter_id:   # no ID sent: nothing to compare
            self.foreign = None
            return True
        if self.adopt or (self.meter_id is None and self._continues(r)):
            self._claim(mid)
            self.foreign = None
            return True
        self.foreign = mid
        if mid not in self._warned:
            self._warned.add(mid)
            why = (f"belongs to meter {self.meter_id}" if self.meter_id else
                   "has readings whose counters don't match this meter's")
            print(f"meter {mid} is connected, but {self.path} {why}. Showing it live without "
                  f"logging. To log it, start with --db pointing at another file, "
                  f"e.g. --db data/{re.sub(r'[^A-Za-z0-9_-]', '_', mid)}.sqlite", flush=True)
        return False

    def add(self, r):  # called from the reader thread only
        if not r.get("logging", True):
            self.window = []
            return
        if r["p_in"] is not None:
            self.window.append(r["p_in"])
        if not hasattr(self, "_last"):
            self._last = 0.0
        if r["ts"] - self._last < LOG_EVERY:
            return
        if self.wcon is None:
            self.wcon = self.connect()
        w = self.window
        p_max = max(w) if w else None
        self.wcon.execute(
            "INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["ts"], sum(w) / len(w) if w else None, p_max, r["p_out"], r["v"], r["a"],
             *r["imp"], *r["exp"], r["tariff"]),
        )
        if self.prev is None or r["ts"] > self.prev[0]:  # never count the same moment twice
            self._accumulate(self.wcon, self.prev, r["ts"], list(r["imp"]), r["tariff"], p_max)
            self.prev = (r["ts"], list(r["imp"]), r["tariff"])
        self.wcon.commit()
        self._last, self.window = r["ts"], []

    def close(self):
        if self.wcon is not None:
            self.wcon.close()
            self.wcon = None

    def reset_window(self):
        """Drop power samples from before a reconnect, so they aren't averaged into the next row."""
        self.window = []

    def history(self, seconds):
        bucket = max(LOG_EVERY, int(seconds // 400))
        con = self.connect()
        rows = con.execute(
            "SELECT CAST(ts/? AS INT)*? AS b, AVG(p_in), MAX(p_max) FROM readings "
            "WHERE ts >= ? GROUP BY b ORDER BY b",
            (bucket, bucket, time.time() - seconds),
        ).fetchall()
        con.close()
        return {"bucket": bucket,
                "points": [[b, round(a or 0, 1), round(m or 0, 1)] for b, a, m in rows]}

    def recent(self, since, until):
        """10-second averages between since and until, as [ts, W, 1] (1 = averaged),
        used to fill the 10-minute chart after a server restart."""
        con = self.connect()
        rows = con.execute(
            "SELECT ts, p_in FROM readings WHERE ts >= ? AND ts < ? ORDER BY ts", (since, until)
        ).fetchall()
        con.close()
        return [[round(ts - LOG_EVERY / 2, 1), round(w, 1), 1] for ts, w in rows if w is not None]

    def stats(self):
        """Logger summary. Reads only the small summary tables and the primary-key ends."""
        con = self.connect()
        # Two separate queries: SQLite only uses the index for a lone MIN() or MAX().
        first = con.execute("SELECT MIN(ts) FROM readings").fetchone()[0]
        last = con.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
        rows, t1, t2, t3 = con.execute(
            "SELECT COALESCE(SUM(n), 0), SUM(t1), SUM(t2), SUM(t3) FROM hours").fetchone()
        changes = con.execute(
            "SELECT ts, prev, tariff FROM tariff_changes ORDER BY ts DESC LIMIT 50").fetchall()
        con.close()
        size = sum(os.path.getsize(p) for p in (self.path, self.path + "-wal") if os.path.exists(p))
        return {
            "rows": rows, "first": first, "last": last, "bytes": size, "path": self.path,
            "file": os.path.relpath(self.path, HERE) if self.path.startswith(HERE + os.sep) else self.path,
            "meter_id": self.meter_id, "foreign": self.foreign,
            "tariff_changes": [{"ts": t, "from": a, "to": b} for t, a, b in changes],
            "tariff_secs": {str(k): v for k, v in ((1, t1), (2, t2), (3, t3)) if v},
        }

    def plans(self, prices, days):
        try:
            with open(os.path.join(HERE, "plans.json"), encoding="utf-8") as fh:
                spec = json.load(fh)
        except (OSError, ValueError) as err:
            return {"error": f"plans.json: {err}"}
        plans = spec["plans"]
        covered = kwh = cost = 0.0
        in_cost = [0.0] * len(plans)
        in_kwh = [0.0] * len(plans)
        first = last = None
        dow_seen = set()
        con = self.connect()
        rows = con.execute(
            "SELECT hour_ts, dow, hour, d1, d2, d3, secs FROM hours WHERE hour_ts >= ? AND secs > 0 "
            "ORDER BY hour_ts", (time.time() - days * 86400,)).fetchall()
        con.close()
        # Plan windows start and end on whole hours, so hourly sums are exact.
        for hts, sd, hour, d1, d2, d3, secs in rows:
            d = (d1, d2, d3)
            e, c = sum(d), sum(d[k] * prices[k] for k in range(3))
            covered += secs; kwh += e; cost += c
            first = first or hts; last = hts
            dow_seen.add(sd)
            for i, p in enumerate(plans):
                if in_window(sd, hour, p):
                    in_cost[i] += c; in_kwh[i] += e
        month = 30.44 * 86400
        out = []
        for i, p in enumerate(plans):
            save = in_cost[i] * p["discount"] / 100
            out.append({**p,
                        "share": in_kwh[i] / kwh if kwh else None,
                        "saved": save,
                        "per_month": save / covered * month if covered else None,
                        "effective": save / cost * 100 if cost else None})
        out.sort(key=lambda r: -(r["per_month"] or 0))
        return {
            "source": spec.get("source"), "notes": spec.get("notes", []),
            "covered_s": covered, "first": first, "last": last, "days_seen": len(dow_seen),
            "kwh": kwh, "cost": cost,
            "cost_per_month": cost / covered * month if covered else None,
            "plans": out,
        }

    def hourly(self, day: date):
        """kWh per local hour label (0-23) for one local day. A day can have 23 or 25 hours:
        the skipped hour stays empty and the repeated hour's two halves add up."""
        start = datetime.combine(day, dtime()).timestamp()
        end = datetime.combine(day + timedelta(days=1), dtime()).timestamp()
        con = self.connect()
        rows = con.execute(
            "SELECT hour, d1, d2, d3, n, p_max, p_max_ts FROM hours WHERE hour_ts >= ? AND hour_ts < ?",
            (start, end)).fetchall()
        first = con.execute(
            "SELECT ts, i1, i2, i3 FROM readings WHERE ts >= ? AND ts < ? ORDER BY ts LIMIT 1",
            (start, end)).fetchone()
        con.close()
        hours = [None] * 24
        peak = None
        for hour, d1, d2, d3, n, p_max, p_max_ts in rows:
            if n or d1 or d2 or d3:
                cur = hours[hour] or [0.0, 0.0, 0.0]
                hours[hour] = [round(cur[0] + d1, 4), round(cur[1] + d2, 4), round(cur[2] + d3, 4)]
            if p_max is not None and (peak is None or p_max > peak["w"]):
                peak = {"ts": p_max_ts, "w": p_max}
        return {
            "start": start,
            "hours": hours,
            "first": {"ts": first[0], "total": round(sum(x or 0 for x in first[1:4]), 3),
                      "regs": [x or 0 for x in first[1:4]]} if first else None,
            "peak": peak,
        }


# ---------------------------------------------------------------- serial reader
def open_port(dev):
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = termios.IGNBRK
    a[1] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[3] = 0
    a[4] = a[5] = termios.B115200
    termios.tcsetattr(fd, termios.TCSANOW, a)
    termios.tcflush(fd, termios.TCIFLUSH)
    return fd


# Where USB serial P1 cables appear: macOS, then Linux (stable by-id names first).
PORT_GLOBS = ["/dev/cu.usbserial*", "/dev/serial/by-id/*FTDI*", "/dev/serial/by-id/*FT232*", "/dev/ttyUSB*"]


def find_port():
    for pattern in PORT_GLOBS:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[0]
    return None


def handle_telegram(tele, hub, store):
    """Parse, publish and log one telegram. Never raises: one odd telegram must not
    stop the reader while the web server keeps serving a frozen reading."""
    try:
        rec = parse(tele)
        if not rec:
            hub.bad += 1
            return
        hub.ok += 1
        hub.raw, hub.raw_ts = tele.decode("ascii", "replace"), rec["ts"]
        try:
            rec["logging"] = store.check_meter(rec)
            rec["log_meter"] = store.meter_id
        finally:
            hub.publish(rec)  # the live view gets the reading even if the check fails
        store.add(rec)
    except Exception as err:  # noqa: BLE001 - logged and counted, reading continues
        hub.errors += 1
        hub.last_error = (time.time(), f"{type(err).__name__}: {err}")
        if hub.errors <= 5 or hub.errors % 100 == 0:
            print(f"telegram error #{hub.errors}: {hub.last_error[1]}", flush=True)


def reader_supervisor(port, hub, store):
    """Restart the reader if it ever dies, instead of leaving the server frozen."""
    while True:
        try:
            reader(port, hub, store)
        except Exception as err:  # noqa: BLE001
            hub.errors += 1
            hub.last_error = (time.time(), f"reader crashed: {type(err).__name__}: {err}")
            print(hub.last_error[1], flush=True)
            time.sleep(2)


def reader(port, hub, store):
    last_err = None
    while True:
        dev = port or find_port()
        if not dev:
            time.sleep(2)
            continue
        try:
            fd = open_port(dev)
        except OSError as err:
            if str(err) != last_err:  # log once, not every retry
                last_err = str(err)
                hint = " (on Linux, add your user to the 'dialout' group)" if isinstance(err, PermissionError) else ""
                print(f"cannot open {dev}: {err}{hint}", flush=True)
            time.sleep(2)
            continue
        last_err = None
        print(f"reading {dev}", flush=True)
        hub.device = dev
        store.reset_window()
        buf = b""
        try:
            while True:
                if not select.select([fd], [], [], 5)[0]:
                    continue
                try:
                    chunk = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    raise OSError("device closed")
                buf += chunk
                while True:
                    s = buf.find(b"/")
                    if s < 0:
                        buf = b""
                        break
                    e = buf.find(b"!", s)
                    if e < 0 or len(buf) < e + 5:
                        buf = buf[s:][-16384:]
                        break
                    tele, buf = buf[s:e + 5], buf[e + 5:]
                    handle_telegram(tele, hub, store)
        except OSError as err:
            print(f"serial: {err}; retrying", flush=True)
            try:
                os.close(fd)
            except OSError:
                pass
            time.sleep(2)


# ---------------------------------------------------------------- price config
DEFAULT_CFG = {"currency": "\u20aa", "prices": [0.6352, 0.6352, 0.6352], "estimated": True}  # IEC flat rate incl. VAT, 1 Jul 2026


class Config:
    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()

    def get(self):
        try:
            with open(self.path) as fh:
                c = json.load(fh)
            return {**DEFAULT_CFG, **c}
        except (OSError, ValueError):
            return dict(DEFAULT_CFG)

    def set(self, data):
        prices = data.get("prices")
        cur = str(data.get("currency", "\u20aa")).strip()[:3] or "\u20aa"
        if (not isinstance(prices, list) or len(prices) != 3 or
                not all(isinstance(p, (int, float)) and 0 <= p < 100 for p in prices)):
            raise ValueError("prices must be three numbers between 0 and 100")
        cfg = {"currency": cur, "prices": [round(float(p), 4) for p in prices], "estimated": False}
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        return cfg


# ---------------------------------------------------------------- http
def host_allowed(host_header, extra=()):
    """Accept a Host header naming this machine: an IP address, localhost, this computer's
    name (or name.local), or a name passed with --allow-host. Anything else, such as an
    attacker's domain re-pointed at 127.0.0.1 (DNS rebinding), is refused."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):                     # [::1]:8765
        host = host[1:host.find("]")] if "]" in host else host
    elif host.count(":") == 1:                   # 127.0.0.1:8765, name:8765
        host = host.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    me = socket.gethostname().lower().split(".")[0]
    names = {"localhost", me, me + ".local", *(h.lower() for h in extra)}
    return host in names


def make_handler(hub, store, config, allow_hosts=()):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def refuse_foreign_host(self):
            if host_allowed(self.headers.get("Host"), allow_hosts):
                return False
            self.send_error(403, "unknown Host; start the server with --allow-host NAME to allow it")
            return True

        def send_json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.refuse_foreign_host():
                return
            if urlparse(self.path).path != "/api/config":
                return self.send_error(404)
            # Browsers send a simple cross-site POST only as text/plain or a form, and always
            # with an Origin header: requiring JSON and a same-origin Origin blocks other pages.
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self.send_error(415, "Content-Type must be application/json")
            origin = self.headers.get("Origin")
            if origin is not None and urlparse(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
                return self.send_error(403, "cross-origin request refused")
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > 4096:
                    raise ValueError("body too large")
                self.send_json(config.set(json.loads(self.rfile.read(n))))
            except (ValueError, TypeError, AttributeError) as err:
                self.send_error(400, str(err))

        def do_GET(self):
            if self.refuse_foreign_host():
                return
            try:
                self.route_get()
            except ValueError as err:
                self.send_error(400, f"bad request: {err}")
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as err:  # noqa: BLE001
                print(f"GET {self.path}: {type(err).__name__}: {err}", flush=True)
                self.send_error(500)

        def route_get(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/index.html", "/about", "/about.html"):
                page = "about.html" if u.path.startswith("/about") else "index.html"
                with open(os.path.join(HERE, page), "rb") as fh:
                    body = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/config":
                self.send_json(config.get())
            elif u.path == "/api/meta":
                self.send_json({
                    "raw": hub.raw, "raw_ts": hub.raw_ts, "ok": hub.ok, "bad": hub.bad,
                    "device": hub.device, "started": hub.started, "now": time.time(),
                    "age": None if hub.raw_ts is None else round(time.time() - hub.raw_ts, 1),
                    "errors": hub.errors, "last_error": hub.last_error,
                    "db": store.stats(),
                })
            elif u.path == "/api/recent":
                with hub.cv:
                    live, latest = list(hub.recent), hub.latest
                # After a restart memory holds less than 15 min: fill the start from SQLite.
                now = time.time()
                start = live[0][0] if live else now
                older = store.recent(now - RECENT_S, start - 1) if start > now - RECENT_S + 5 else []
                self.send_json({"points": older + [list(p) for p in live], "latest": latest})
            elif u.path == "/api/history":
                secs = min(max(int(q.get("seconds", ["3600"])[0]), 600), 31 * 86400)
                self.send_json(store.history(secs))
            elif u.path == "/api/plans":
                days = min(max(float(q.get("days", ["28"])[0]), 1), 366)
                self.send_json(store.plans(config.get()["prices"], days))
            elif u.path == "/api/hourly":
                d = q.get("date", [None])[0]
                self.send_json(store.hourly(date.fromisoformat(d) if d else date.today()))
            elif u.path == "/api/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                seq = -1
                try:
                    while True:
                        rec, seq = hub.wait(seq, 15)
                        msg = f"data: {json.dumps(rec)}\n\n" if rec else ": ping\n\n"
                        self.wfile.write(msg.encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
            else:
                self.send_error(404)

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="serial device (default: auto-detect, see PORT_GLOBS)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--http", type=int, default=8765)
    ap.add_argument("--db", default=os.path.join(HERE, "data", "p1.sqlite"))
    ap.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                    help="extra host name the dashboard may be opened as (IP addresses, localhost "
                         "and this computer's name are always allowed); repeatable")
    ap.add_argument("--adopt-meter", action="store_true",
                    help="give the log to the next meter seen, even if it belongs to another meter, e.g. after "
                         "IEC replaces yours (normally a log keeps the meter it first saw and ignores others)")
    args = ap.parse_args()

    hub, store = Hub(), Store(args.db, adopt=args.adopt_meter)
    threading.Thread(target=reader_supervisor, args=(args.port, hub, store), daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.http), make_handler(hub, store, Config(os.path.join(HERE, "config.json")), args.allow_host))
    srv.daemon_threads = True
    print(f"dashboard: http://{'127.0.0.1' if args.host == '127.0.0.1' else args.host}:{args.http}", flush=True)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("warning: listening beyond this computer. Anyone on the network can view your usage "
              "and change prices; there is no password.", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
