# IEC Kaifa P1 dashboard

A local, live electricity dashboard for Israel Electric Corporation (IEC) **Kaifa** smart meters, read through the **P1 port** (DSMR 5.0) with a USB cable. Developed on a single-phase **MA110M**; the 3-phase **MA309M** uses the same codes and shows per-phase voltage and current.

- Live power, voltage and current, updated every second
- Today's kWh, cost and peak
- Power chart (10 min / 1 h / 24 h / 7 d)
- Hourly energy split by tariff counter
- IEC flat and time-of-use prices
- A comparison of private supplier plans against your own usage
- A meter details page with every register and the raw telegram

Python standard library only: no packages to install, no cloud, and data stays on your machine.

## Hardware

- An IEC Kaifa MA110M (single-phase) or MA309M (3-phase) meter. The P1 port is the RJ12 socket behind the unsealed flap, and it must be active (it was on the meter this was built on).
- A P1 USB cable (FTDI FT232RL, RJ12, inverted serial, "Dutch smart meter P1 cable"). macOS and Linux include the driver. A plain USB-serial adapter won't work: the P1 signal is inverted.
- macOS or Linux (e.g. a Raspberry Pi). Windows is not supported: the serial code uses `termios`.

The port sends **115200 8N1, inverted**, one telegram per second, with Israeli tariff codes `1-0:1.8.11 / .12 / .13`. See [`METER.md`](METER.md) §3–4.

## Quick start

```sh
python3 server.py            # auto-detects the cable (macOS /dev/cu.usbserial*, Linux /dev/serial/by-id/*FTDI* or /dev/ttyUSB*)
open http://127.0.0.1:8765
```

| Option | Default | |
|---|---|---|
| `--port` | auto-detect | Serial device |
| `--host` | `127.0.0.1` | `0.0.0.0` to open it from a phone on your Wi-Fi network (no authentication) |
| `--http` | `8765` | Web port |
| `--db` | `data/p1.sqlite` | SQLite log, one row per 10 s |

Unplugging the cable is fine: the server keeps serving and resumes within about 2 s of the cable returning.

**Linux:** your user needs access to the serial device. Run `sudo usermod -aG dialout $USER`, then log out and back in. The server logs a hint if it gets "permission denied".

**3-phase meters:** the dashboard shows voltage and current per phase (L1 / L2 / L3). The SQLite log keeps L1 voltage and current; energy, power and cost cover all phases.

## Run at login (macOS)

On Linux, use a systemd user service or cron `@reboot` instead.

```sh
REPO="$PWD"; PY="$(command -v python3)"
sed -e "s#__PYTHON__#$PY#g" -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME#g" \
    launchd/local.iec-kaifa-p1-dashboard.plist > ~/Library/LaunchAgents/local.iec-kaifa-p1-dashboard.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.iec-kaifa-p1-dashboard.plist
```

| Task | Command |
|---|---|
| Restart after code changes | `launchctl kickstart -k gui/$(id -u)/local.iec-kaifa-p1-dashboard` |
| Stop | `launchctl bootout gui/$(id -u)/local.iec-kaifa-p1-dashboard` |
| Log | `~/Library/Logs/iec-kaifa-p1-dashboard.log` |

Logging pauses while the Mac sleeps. See [`ESP32-READER.md`](ESP32-READER.md) for an always-on reader.

## Prices and plans

- **Prices:** set per tariff counter with the **Price** button. They are saved to `config.json`. The button offers presets for the IEC flat rate and this season's IEC time-of-use prices.
- **Supplier plans:** the comparison card reads [`plans.json`](plans.json). Edit it when offers change; no restart needed.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/stream` | Server-Sent Events, one parsed telegram per second |
| `GET /api/recent` | Last 15 min, plus the latest reading. 1-second points from memory; after a restart the earlier part comes from the 10-second log, flagged as averages |
| `GET /api/history?seconds=N` | Bucketed average and peak power |
| `GET /api/hourly?date=YYYY-MM-DD` | kWh per hour per tariff counter |
| `GET /api/plans?days=N` | Supplier plan savings projected from logged usage |
| `GET /api/meta` | Raw telegram, link stats, logger stats |
| `GET` / `POST /api/config` | Prices and currency |

## Files

| Path | |
|---|---|
| `server.py` | Serial reader, CRC check, SQLite logger, web server |
| `index.html` | Dashboard |
| `about.html` | Meter details page |
| `plans.json` | Supplier offers for the plan comparison |
| `launchd/` | Login-item template |
| `tests/` | Unit tests (stdlib `unittest`) and a masked sample telegram |
| [`METER.md`](METER.md) | Everything known about the meter, the P1 port, IEC tariffs and official documentation |
| [`ESP32-READER.md`](ESP32-READER.md) | Parts, wiring and plan for a standalone ESP32 P1 reader |
| `reference/` | Datasheets, standards, certificates, tariffs, and a redacted meter photo |
| `data/`, `config.json` | Your usage log and prices. Created at runtime and **git-ignored** |

## Tests

```sh
python3 -m unittest discover -s tests
```

## Licence

MIT. See [`LICENSE`](LICENSE). Documents in `reference/` belong to their publishers.

## Disclaimer

Not affiliated with IEC or Kaifa. The P1 port is read-only and opto-isolated: only open the unsealed P1 flap, never the sealed covers. Prices and plans are a snapshot; check current rates.
