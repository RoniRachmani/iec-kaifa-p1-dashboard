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
import json
import os
import re
import select
import sqlite3
import termios
import threading
import time
from collections import deque
from datetime import date, datetime, time as dtime
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
"""


class Store:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = self.connect()
        con.executescript(SCHEMA)
        con.close()
        self.wcon = None
        self.window = []  # p_in samples since last row

    def connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def add(self, r):  # called from the reader thread only
        if r["p_in"] is not None:
            self.window.append(r["p_in"])
        if not hasattr(self, "_last"):
            self._last = 0.0
        if r["ts"] - self._last < LOG_EVERY:
            return
        if self.wcon is None:
            self.wcon = self.connect()
        w = self.window or [r["p_in"]]
        self.wcon.execute(
            "INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["ts"], sum(w) / len(w), max(w), r["p_out"], r["v"], r["a"],
             *r["imp"], *r["exp"], r["tariff"]),
        )
        self.wcon.commit()
        self._last, self.window = r["ts"], []

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
        con = self.connect()
        rows, first, last = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM readings").fetchone()
        changes = con.execute(
            "SELECT ts, prev, tariff FROM (SELECT ts, tariff, LAG(tariff) OVER (ORDER BY ts) AS prev "
            "FROM readings) WHERE prev IS NOT NULL AND prev != tariff ORDER BY ts DESC LIMIT 50"
        ).fetchall()
        share = con.execute("SELECT tariff, COUNT(*) FROM readings GROUP BY tariff").fetchall()
        con.close()
        size = sum(os.path.getsize(p) for p in (self.path, self.path + "-wal") if os.path.exists(p))
        return {
            "rows": rows, "first": first, "last": last, "bytes": size, "path": self.path,
            "tariff_changes": [{"ts": t, "from": a, "to": b} for t, a, b in changes],
            "tariff_rows": {str(t): n for t, n in share},
        }

    def energy_intervals(self, since):
        """Yield (mid_ts, [dkWh per import register]) for consecutive logged rows.
        Gaps longer than MAX_GAP (cable out, Mac asleep) are skipped: we can't tell
        when inside the gap that energy was used."""
        con = self.connect()
        cur = con.execute("SELECT ts, i1, i2, i3 FROM readings WHERE ts >= ? ORDER BY ts", (since,))
        prev = None
        for ts, *regs in cur:
            regs = [r or 0.0 for r in regs]
            if prev and 0 < ts - prev[0] <= MAX_GAP:
                d = [max(0.0, regs[k] - prev[1][k]) for k in range(3)]
                yield (ts + prev[0]) / 2, ts - prev[0], d
            prev = (ts, regs)
        con.close()

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
        for mid, dt, d in self.energy_intervals(time.time() - days * 86400):
            lt = datetime.fromtimestamp(mid)
            sd = (lt.weekday() + 1) % 7          # 0 = Sunday
            hour = lt.hour + lt.minute / 60
            e, c = sum(d), sum(d[k] * prices[k] for k in range(3))
            covered += dt; kwh += e; cost += c
            first = first or mid; last = mid
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
        start = datetime.combine(day, dtime()).timestamp()
        con = self.connect()
        rows = con.execute(
            "SELECT ts, i1, i2, i3, p_max FROM readings WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start, start + 86400 + 3600),
        ).fetchall()
        con.close()
        first, last = {}, {}
        for ts, i1, i2, i3, _ in rows:
            h = int((ts - start) // 3600)
            regs = (i1 or 0, i2 or 0, i3 or 0)
            first.setdefault(h, regs)
            last[h] = regs
        hours = []
        for h in range(24):
            if h not in first:
                hours.append(None)
                continue
            end = first.get(h + 1, last[h])
            hours.append([round(max(0.0, end[k] - first[h][k]), 4) for k in range(3)])
        today = [r for r in rows if r[0] < start + 86400]
        peak = max(today, key=lambda r: r[4] or 0) if today else None
        return {
            "start": start,
            "hours": hours,
            "first": {"ts": today[0][0], "total": round(sum(x or 0 for x in today[0][1:4]), 3),
                      "regs": [x or 0 for x in today[0][1:4]]}
            if today else None,
            "peak": {"ts": peak[0], "w": peak[4]} if peak else None,
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
                    rec = parse(tele)
                    if not rec:
                        hub.bad += 1
                    if rec:
                        hub.ok += 1
                        hub.raw, hub.raw_ts = tele.decode("ascii", "replace"), rec["ts"]
                        hub.publish(rec)
                        try:
                            store.add(rec)
                        except sqlite3.Error as err:
                            print("sqlite:", err, flush=True)
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
def make_handler(hub, store, config):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send_json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if urlparse(self.path).path != "/api/config":
                return self.send_error(404)
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > 4096:
                    raise ValueError("body too large")
                self.send_json(config.set(json.loads(self.rfile.read(n))))
            except (ValueError, TypeError, AttributeError) as err:
                self.send_error(400, str(err))

        def do_GET(self):
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
    args = ap.parse_args()

    hub, store = Hub(), Store(args.db)
    threading.Thread(target=reader, args=(args.port, hub, store), daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.http), make_handler(hub, store, Config(os.path.join(HERE, "config.json"))))
    srv.daemon_threads = True
    print(f"dashboard: http://{'127.0.0.1' if args.host == '127.0.0.1' else args.host}:{args.http}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
