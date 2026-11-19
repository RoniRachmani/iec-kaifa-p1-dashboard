# Smart meter & P1 port: everything we know

_Started 14 Nov 2026 from a photo of the meter, the cable's datasheet, raw P1 captures (40+ telegrams, every CRC valid), the macOS USB registry and the dashboard's logger. Later extended with IEC tariffs, supplier plans and official documentation (§8–9). Code and setup: see [`README.md`](../README.md)._

## Summary

- **Meter:** Kaifa **MA110M**, single-phase, made in 2025, with a cellular (2G/3G/4G) comms module.
- **P1 port:** active, **unencrypted, DSMR 5.0 plain text**, **115200 baud 8N1**, one telegram per second, 475 bytes each, CRC16 verified.
- **Cable:** genuine FTDI FT232RL. It uses macOS's built-in driver, so nothing was installed.
- **Non-Dutch twist:** **three** tariff registers (`x.8.11` / `x.8.12` / `x.8.13`) instead of the Dutch two (`x.8.1` / `x.8.2`), plus a one-entry interval log (`99.1.0`). Standard DSMR integrations may miss the kWh totals.
- **A second MA110M** in another flat sends exactly the same telegram format (§10), so everything here applies to it too.
- **History over P1:** none beyond the last interval. Lifetime totals are available. Detailed history lives in the meter (encrypted, not readable by us; §9) and with IEC (online personal area).

---

## 1. Meter: from the nameplate photo

| Item | Value |
|---|---|
| Manufacturer | Kaifa: Shenzhen Kaifa Technology (Chengdu) Co., Ltd., No. 99 Tianquan Rd., Hi-Tech Development Zone, Chengdu, P.R.C. |
| Model | **MA110M**, variant code `H23LCDE` |
| Barcode / serial on the front | **2557xxxx** (printed twice, top and middle) |
| Comms module | **2G+3G+4G Module CL102K** (top slot, sealed screw) |
| Type | **1P.2W**: single phase, 2-wire |
| Current | **0.25–5(60) A**: minimum 0.25 A, reference 5 A, maximum 60 A |
| Voltage / frequency | 230 V, 50 Hz |
| Standards | IEC 62052-11 · IEC 62053-21 Cl.1 · EN 50470-3 Cl.B (accuracy class B ≈ 1 %) |
| Metrology marking | `CE` + `M25` + `0122` (MID mark: year 2025, notified-body number 0122); `T12100` printed above it |
| Other marks | CE, `(5111)`, `(067)`, the DLMS logo, the WEEE bin, IP 54 |
| Operating temperature | −25 °C … +55 °C |
| Test LED constant | **2000 imp/kWh**: each LED flash = 0.5 Wh |
| Year | 2025 · Made in China |
| Ports | **P1 Port** (RJ12 socket behind a flip cover, bottom right, **not sealed**) · round **optical (IR) port** in the centre |
| Buttons | Two orange buttons on the right; the lower one is sealed (`DT`) |
| Display annunciators | `L1`, tariff `T3`, signal bars, energy-direction arrows (+P / −Q), `RO OM OT RE Mag` flags, `Status` LED |
| Display at the time of the photo | `1.8.0` = **002996 kWh**, `L1`, `T3` |

> **Two different IDs:** the barcode says **2557xxxx**, but the P1 equipment ID (`0-0:96.1.1`) is **K06xxx**. The utility may use either on bills, so keep both.

## 2. The cable

| Item | Value |
|---|---|
| Product | "Dutch Smart Meter P1 Port Cable" (FTDI FT232RL, RJ11 6P4C/6P6C, DSMR/ESMR) |
| USB IDs | Vendor **0x0403** (FTDI), product **0x6001** (FT232R), bcdDevice 0x0600 |
| USB product / serial | `FT232R USB UART` / **FTxxxxxx** |
| Speed | USB Full Speed (12 Mbit/s) |
| macOS driver | Apple's built-in **DriverKit AppleUSBFTDI** (`com.apple.DriverKit-AppleUSBFTDI`); **no FTDI driver installed** |
| Device node | **`/dev/cu.usbserial-XXXXXXXX`** |
| Wiring (per datasheet) | P1 pin 5 (data, open-collector, inverted) → FT232RL RXD via the cable's inverter; pin 3 → GND; pin 2 (data request) wired for DSMR v4; pin 1 +5 V optional |
| Datasheet notes | Lists the Kaifa MA105, not the MA110M; "compatibility with smart meters from other countries is not guaranteed". **It works with this meter anyway.** |
| Host | macOS 27.2.1 (build 26B131) |

## 3. P1 interface: what we measured

| Property | Result |
|---|---|
| Serial settings | **115200 baud, 8 data bits, no parity, 1 stop bit (8N1)** |
| 9600 7E1 (DSMR v4) | No data |
| Request line | Not needed; the meter pushes data continuously |
| Rate | **1 telegram per second** |
| Size | **475 bytes**, constant |
| Encoding | ASCII text; **not encrypted**, no key needed |
| Integrity | CRC16 (poly 0xA001, over `/` … `!`, inclusive); **every captured telegram valid** |
| Header | `/KFM5KAIFA-METER` (`KFM` = Kaifa's manufacturer code, `5` = 115200-baud mode) |
| Protocol version | `1-3:0.2.8(50)` = **DSMR / P1 5.0** |
| Port activation | Already active. Nothing was requested from the utility. |

### Sample telegram (captured 01:24:56)

```
/KFM5KAIFA-METER

1-3:0.2.8(50)
0-0:1.0.0(261114012456W)
0-0:96.1.1(K06xxx)
1-0:1.8.11(000699.801*kWh)
1-0:1.8.12(000000.000*kWh)
1-0:1.8.13(002296.806*kWh)
1-0:2.8.11(000000.000*kWh)
1-0:2.8.12(000000.000*kWh)
1-0:2.8.13(000000.000*kWh)
0-0:96.14.1(03)
1-0:1.7.0(00.380*kW)
1-0:2.7.0(00.000*kW)
0-0:96.13.0()
1-0:32.7.0(240.0*V)
1-0:31.7.0(001.7*A)
1-0:99.1.0(1)(0-0:96.10.7)(1-0:1.29.0)(1-0:2.29.0)(261114011500W)(00)(000000.065*kWh)(000000.000*kWh)
!598C
```

## 4. Field reference (OBIS codes)

| OBIS code | Meaning | Value seen | Resolution / notes |
|---|---|---|---|
| `1-3:0.2.8` | P1 protocol version | `50` → v5.0 | |
| `0-0:1.0.0` | Meter clock | `261114012456W` → 2026-11-14 01:24:56 | `YYMMDDhhmmss` + `W` winter / `S` summer. Agreed with the Mac's clock to the second. |
| `0-0:96.1.1` | Equipment identifier | `K06xxx` | Plain ASCII (Dutch meters hex-encode this field) |
| `1-0:1.8.11` | Imported energy, **tariff 1** | 699.801 kWh | 1 Wh resolution; didn't change during capture |
| `1-0:1.8.12` | Imported energy, **tariff 2** | 0.000 kWh | Never used so far |
| `1-0:1.8.13` | Imported energy, **tariff 3** | 2,296.744 → 2,296.806 kWh | Rising (the active tariff) |
| `1-0:2.8.11/12/13` | Exported energy, tariffs 1–3 | 0 / 0 / 0 kWh | No export (no solar feed-in) |
| `0-0:96.14.1` | Active tariff | `03` | Matches `T3` on the display |
| `1-0:1.7.0` | Power being imported now | 0.380–0.390 kW | **10 W steps** |
| `1-0:2.7.0` | Power being exported now | 0.000 kW | |
| `0-0:96.13.0` | Text message from the utility | empty | |
| `1-0:32.7.0` | Voltage, L1 | 239.0–240.0 V | Shows 0.1 V digits, but varied in whole volts |
| `1-0:31.7.0` | Current, L1 | 1.7 A | 0.1 A steps |
| `1-0:99.1.0` | Interval log ("load profile") | **1 entry**: interval ending **01:15:00**, status `00`, import 0.065 kWh, export 0.000 kWh | Captures `1-0:1.29.0` / `1-0:2.29.0` (energy per interval). Same entry from 01:15 through 01:25, so the interval is probably **15 min**; confirm when it changes at 01:30. |

**Energy check:** 699.801 + 0 + 2,296.744 = **2,996.545 kWh**, matching `1.8.0 = 002996` on the display (the display truncates).

**Fields a Dutch DSMR 5 meter sends that this one does not:** power-failure counters (`96.7.21`, `96.7.9`), power-failure event log (`99.97.0`), voltage sag/swell counters (`32.32.0`, `32.36.0`), per-phase power (`21.7.0` / `22.7.0`), gas or water M-Bus readings (`0-n:24.2.1`), and the text code (`96.13.1`).

## 5. How much history the meter exposes

| Source | What you get | How far back |
|---|---|---|
| P1 telegram, live values | Power, voltage, current, tariff | Now only |
| P1 lifetime counters | kWh per tariff, import and export | **Since installation**, as totals (no timing) |
| P1 `99.1.0` | Energy in the last interval | **One interval** (probably 15 min) |
| Dashboard logger (`data/p1.sqlite`) | 10-second averages + counters | From **2026-11-14 01:20:21**, while the server runs |
| Meter's internal memory | Billing values: **31 days** of daily and **12 months** of monthly, plus load profiles (per the type approval, §9) | Optical port, RS-485 and the cellular module only. All are encrypted with factory-generated keys, so not readable by us. |
| Utility online account | Interval data sent over the CL102K cellular module | Usually back to installation. **This is the realistic source of past history.** |

Gaps in logging don't lose energy totals: the next reading's counters show exactly how many kWh passed, just not when within the gap.

## 6. The dashboard

Files, quick start, options, API and the login-item install are in [`README.md`](../README.md). Tests: `python3 -m unittest discover -s tests`.

This Mac runs it as the launch agent `local.iec-kaifa-p1-dashboard` (installed from `deploy/launchd/`). It starts at login, restarts if it crashes, and logs to `~/Library/Logs/iec-kaifa-p1-dashboard.log`. Logging pauses while the Mac sleeps or is logged out. When the cable is unplugged, it keeps serving the page and resumes within about 2 s of the cable returning.

**Database schema:** `readings(ts, p_in, p_max, p_out, v, a, i1, i2, i3, e1, e2, e3, tariff)`. Here `p_in` is the 10-second average in W, `p_max` the 10-second peak, `i1–3` / `e1–3` the import / export counters in kWh, and `ts` Unix time.

**Summary tables** (kept up to date on every write; rebuilt automatically from `readings` if missing):
- `hours`: one row per local clock hour, holding kWh per counter, seconds covered, seconds on each tariff, row count and the hour's peak. It is keyed by the hour's real start time, so the 23- and 25-hour daylight-saving days are correct.
- `tariff_changes`: one row per counter switch.

Stats, the plan comparison and the hourly chart read only these, about 8,800 rows a year instead of about 3 million. Live logging only folds in readings newer than the last one, so after writing older readings (e.g. an ESP32 backfill) call `Store.rebuild_summary(since, until)` for that time range.

**Intervals skipped:** gaps over 120 s, a missing counter value, a counter going backwards, and jumps implying more than 100 kW.

**First logged stats (01:20–01:24, 22 rows):** power 380–390 W (average 382 W), voltage 239 V.

## 7. Open questions & next steps

- [x] Confirm the `99.1.0` interval length: **15 min**, seen on the second meter (§10). Same model and format, so very likely the same here.
- [ ] Confirm the counter mapping (T1 = peak, T3 = off-peak): expect a switch to T1 at 17:00 Sun–Thu. It will show under "Counter switches seen" on the About page.
- [ ] Import past usage from IEC's personal area (normally 15-minute data) into `p1.sqlite`, so the plan comparison works immediately (§9.3).
- [x] Run the server automatically on this Mac (launch agent, §6).
- [ ] Always-on logging without the Mac: an ESP32 reader powered by the P1 port's own +5 V (§9.3). Parts list and wiring are in `esp32-reader.md`.
- [ ] For Home Assistant: the built-in DSMR integration may not map `x.8.11–13`; use a custom parser or the dashboard's API instead. For an ESP32 reader, start from [mp3llll/iec-p1-esphome-3phase](https://github.com/mp3llll/iec-p1-esphome-3phase): its ESPHome config has a CRC-checking custom parser written because "the dsmr component does not know the Israeli 1.8.11–13 energy codes", and it ships Home Assistant `configuration.yaml` / `dashboard.yaml`. It was built for the 3-phase MA309M, so drop the L2/L3 sensors for this MA110M. See `esp32-reader.md`.
- [x] Estimated cost: IEC flat rate set (§8), and supplier plan comparison added.
- [ ] Press the meter's unsealed **Display** button (upper orange button) and note which items the LCD cycles through.
- [ ] Cross-check P1 power with the test LED: 2000 blinks per kWh (§9.1).
- [ ] Await Kaifa's reply: emailed `metering@kaifa.cn` on 2026-11-14 asking for the "MA110M and MA309M Meter Family User Manual" (P1 tariff registers `1.8.11–13`, display menu). If there's no answer in about two weeks, follow up or ask IEC (website or 103). Save anything received in `docs/reference/meter/`.

## 8. IEC tariffs (from 1 July 2026, incl. 18% VAT)

Source: [IEC English tariff sheet](reference/tariffs/iec-electricity-tariffs-2026-07.pdf) (tariff update 1726).

**Flat residential rate:** 63.52 ag/kWh (₪0.6352). Fixed charge for a bi-monthly single-phase customer: distribution ₪11.76 + supply ₪18.41 = ₪30.17/month, plus a capacity charge of ₪7.29 per kVA per year. The dashboard is set to ₪0.6352 for all three registers.

**Time-of-use (low voltage), ag/kWh:**

| Season | Months | Peak | Off-peak |
|---|---|---|---|
| Summer | Jun–Sep | 172.23 | 50.42 |
| Winter | Dec–Feb | 114.70 | 46.63 |
| Spring/Autumn | Mar–May, Oct–Nov | 49.58 | 45.78 |

TOU fixed charge for a bi-monthly low-voltage customer: ₪37.88 + ₪18.33 = ₪56.21/month (₪26/month more than flat).

**Peak hours** (Israel time):
- Summer: Sun–Thu 17–23. Fri and Sat are off-peak all day.
- Winter: every day 17–22.
- Spring/Autumn: Sun–Thu 17–22. Fri and Sat are off-peak all day.

Holidays count as Saturday and their eves as Friday.

**Expected register mapping:** T3 is off-peak (observed on Sat 01:20, an autumn off-peak time) and T1 is peak. This is unconfirmed until a Sun–Thu 17:00 switch is logged.

**Supplier plan comparison:** the dashboard card "Supplier plans" (API: `/api/plans?days=28`) applies each offer in `tariffs/plans.json` to the logged usage. See the [July 2026 supplier plans](supplier-plans-2026-07.md) for the offers and their source.

- Energy comes from import-register deltas between consecutive rows. Gaps longer than 120 s are skipped.
- The savings are projected to a month.
- Night windows (23–07) belong to the night they start on (Sun–Thu).
- Edit `tariffs/plans.json` when offers change. No restart is needed.

## 9. Official documentation and what it tells us

There is no public Kaifa datasheet or manual for the MA110M, and no IEC P1 specification turned up. Kaifa's manual is the "MA110M and MA309M Meter Family User Manual", Rev. 1.0, which is not public. The closest official sources, saved in `docs/reference/`:

| File | What it is |
|---|---|
| [Kaifa MA110M type approval](reference/meter/kaifa-ma110m-type-approval-smu-tsk-221-23-146-sk.pdf) | Slovak Metrology Institute type approval TSK 221/23-146 for the MA110M, 19 Oct 2023, valid to 2033. Certificate plus a 16-page assessment report with drawings (in Slovak). [Source](https://www.normoff.gov.sk/files/typovky/tsk/TSK_221_23_146.pdf) |
| [Kaifa MA110M G3-PLC certificate](reference/meter/kaifa-ma110m-g3-plc-certificate-2022.pdf) | G3-PLC (power-line communication) certificate for the MA110M, 14 Jul 2022, HW V1.3, FW V096011. Not relevant to this meter's 4G module. [Source](https://g3-alliance.com/download/75/pdf_certified_products/3296/g3-2207-524-2-c5-g3-plc-certificate-fcc-kaifa-ma110m-for-publication.pdf) |
| [DSMR 5.0.2 P1 Companion Standard](reference/p1/dsmr-5.0.2-p1-companion-standard.pdf) | Netbeheer Nederland DSMR 5.0.2 P1 Companion Standard (26 Feb 2016): the official spec of the P1 port this meter implements. [Source](https://www.netbeheernederland.nl/sites/default/files/2024-02/dsmr_5.0.2_p1_companion_standard.pdf) |

Unofficial but Israel-specific: [yoni03/iec-PlatformIO-3phase](https://github.com/yoni03/iec-PlatformIO-3phase) (MIT) is an ESP32 reader for IEC's Kaifa MA110M / MA309M meters. It uses 115200 baud with CRC checking and the Israeli OBIS codes `1.8.11–13`, matching what we measured. It builds on klimofey/iec-p1-esphome.

### 9.1 From the type approval (MA110M)

**Measurement**
- Measures import and export of active (A±), reactive (R±) and apparent (VA±) energy, plus maximum demand.
- Instantaneous values: voltage, current (optionally neutral current), active, reactive and apparent power, frequency, power factor, and the active quadrant.
- Accuracy: active energy **class B** (EN 50470-3, about ±1%); reactive energy class 1 or 2.
- Starting current 0.004 × Ib = **20 mA (about 5 W)**. Loads below that don't register.
- Current ranges: 0.25–5(60) A, 0.25–5(80) A or 0.5–10(80) A. This meter is 0.25–5(60) A, so up to about 13.8 kW.
- Meter constant 500–10,000 imp/kWh. This meter uses **2000 imp/kWh**: one test-LED blink is 0.5 Wh, so 2.43 kW gives about 1.35 blinks per second.
- Self-consumption ≤ 2 W / 10 VA (without communication), not billed.

**Tariffs and storage**
- Up to **4 tariffs** in two tariff tables (active and passive). Supports workday and weekend schedules, special days and seasons, which is enough to encode IEC's TOU table. T2 and T4 are unused slots here.
- Maximum demand per tariff, with a timestamp.
- Stores billing data for at least one billing period: **31 days** of daily billing values and **12 months** of monthly values, plus up to 4 load profiles.

**Clock**
- Real-time clock per IEC 62054-21, with leap-year and automatic DST support.
- Battery-backed for at least 2 years without mains. Battery life about 5 years, and the battery is replaceable.

**Interfaces and security**
- Modular remote communication: GPRS/4G/LTE-CAT1/LTE-CATM/NB-IoT/PLC/RF. This meter has the 2G/3G/4G CL102K module.
- Local interfaces: optical port, RS-485 and M-Bus.
- Protocol DLMS/COSEM and TCP/IP. **All communication interfaces are encrypted** with authentication, encryption and master keys generated at manufacture. Key changes are logged.
- The P1 port appears in the drawings but not in the interface list. On this meter it is the one unencrypted, read-only output.

**Control, firmware and events**
- Built-in **disconnect relay**: the utility can cut supply remotely, or the meter can when a set power or energy limit is exceeded.
- Firmware updates locally or remotely, each recorded in the event log. The metrology part is separated (WELMEC 7.2).
- Event log with OBIS codes covers power quality, programming, time setting, bypass, **magnetic tampering**, missing phase or neutral, reverse current, and opening of the case, terminal cover or module cover.

**Physical**
- 8-digit segmented LCD, plus a Display (scroll) button and a sealable Test/parameterisation button.
- Glass-filled polycarbonate case, protection class II, IP54.
- Operating range −40 to +70 °C. The nameplate states −25 to +55 °C.
- Seals: module cover, Test button, battery cover, two metrology seals on the case, and the terminal cover. **The P1 cover is not sealed.**
- Slovak re-verification interval is 12 years. Israel's rules may differ.
- Firmware checksums listed: versions 000000, V1100, 000001, 000002, 010001.

**Nameplate codes:** `T12100` matches NMi evaluation report **ER12100** (rev. 7, 28 Oct 2022) cited in the approval. `M25 0122` is the MID metrology mark: year 2025, notified body 0122 (NMi Certin; that body number is from general knowledge, not these documents). Type testing was done by NMi Certin and KEMA in the Netherlands, which fits the Dutch-style P1 port.

### 9.2 From DSMR 5.0.2, and how this meter compares

| Item | DSMR 5.0.2 says | This meter |
|---|---|---|
| Connector | RJ12. Pins: 1 +5 V, 2 Data Request, 3 Data GND, 4 n.c., 5 Data (open collector), 6 Power GND. Must never be sealed | RJ12 behind an unsealed flap ✓ |
| Serial | 115200 baud, 8N1, data line **inverted** | Same. The FTDI cable inverts ✓ |
| Data Request | Pull pin 2 high (4–5.5 V, 4–10 mA) to start. Sending stops when released | Telegram every second while the cable is attached ✓ |
| Rate | One telegram per second, sent within 1 s | 1 per second, 475 bytes ✓ |
| Checksum | CRC16, polynomial x¹⁶+x¹⁵+x²+1, LSB first, no XOR, 4 hex digits after `!` | Matches, all valid ✓ |
| Power to the reader | +5 V, 250 mA continuous, short-circuit limited to 50 mA, galvanically isolated. **Not counted in the kWh registers** | Not used by the FTDI cable. An ESP32 can run from it |
| Power resolution | `1.7.0` in 1 W steps | **10 W steps** (deviation) |
| Tariffs | `1.8.1` = low, `1.8.2` = normal. "Support for up to sixteen tariffs should be included" | Israeli codes `1.8.11 / 1.8.12 / 1.8.13` |
| Tariff indicator | `0-0:96.14.0`, meant for switching tariff-dependent loads such as boilers | Sent as `0-0:96.14.1` |
| Safety | P1 cannot influence the meter: opto-isolated, read-only | Plugging into P1 can't change or tamper with the meter |
| Optional fields | Power-failure counters and log, sag/swell counters, per-phase power, 1024-char text message, M-Bus gas/water | Not sent (§4) |

### 9.3 Practical takeaways

1. **Past history:** the meter's 31-day and 12-month stores and its load profiles are encrypted and reach IEC over 4G, so we can't read them. IEC's personal area (smart-meter readings, normally 15-minute) is the realistic source. If it exports a file, import it into `p1.sqlite` so the plan comparison works straight away.
2. **Display button:** the upper orange button is unsealed and scrolls the LCD. IEC configures what it shows, possibly the per-tariff totals and the date and time. The lower button (Test) is sealed. Don't touch it.
3. **Tamper safety:** the meter logs case, terminal and module-cover openings and magnets. Using the unsealed P1 flap is the intended consumer access.
4. **Standalone reader:** the P1 port supplies 5 V at up to 250 mA, so an ESP32 (Wi-Fi) can be powered straight from it and log 24/7 with no Mac-sleep gaps.
5. **Trust the numbers:** P1 kWh comes from the same class B registers IEC bills from. The only gaps are below the 20 mA starting current and the 10 W power steps.
6. **Format may change:** remote firmware updates could change the P1 output. The parser validates CRC and tolerates missing or renamed fields, but watch the log after any unexplained change.
7. **Relay:** the meter can disconnect supply remotely or on a configured limit. Whether IEC sets a limit for homes is not documented. The 60 A maximum is far above the observed peak (~2.85 kW).

## 10. A second MA110M (another flat)

Read with the same cable and laptop on 14 Nov 2026, 22:19–22:36. The dashboard ran with its own log (`--db data/apartment2.sqlite`), so the two meters' readings never mix (see "One log per meter" in `README.md`).

**Identity.** P1 equipment ID **K06xxx** (masked here as for the home meter; a different ID). The nameplate wasn't photographed.

**Format: identical to the home meter.** Across 31 sampled telegrams:
- Same header `/KFM5KAIFA-METER` and protocol `1-3:0.2.8(50)` (DSMR 5.0).
- Same 16 fields in the same order, nothing added or missing.
- Same size, **475 bytes**, and every CRC valid.
- Same resolution: power in **10 W** steps, current in 0.1 A steps, voltage in whole volts shown with a `.0`.
- Same three-counter layout: T2 unused, no export, active tariff `03` (T3) on a Saturday night, and an empty text message.

**What differs is only the readings:**

| | Home meter | Second meter |
|---|---|---|
| Lifetime import | ~2,997 kWh | ~1,285 kWh (T1 189.062, T3 1,096.0) |
| Share on T1 | 23% | 15% |
| Voltage | 239–240 V | 231–232 V |
| Load when sampled | 380–390 W | 240–360 W |
| Meter clock against the Mac | matched to the second | about 1–1.5 s behind (harmless; display only) |

The lower voltage comes from the local grid, not the meter; both are well within the normal range. The T1 share reflects each home's usage pattern, not the meter.

**Interval log (`99.1.0`).** The entry moved from the interval ending **22:15** to the one ending **22:30**: the interval is **15 minutes**. Its 0.196 kWh agrees with the T3 counter, which rose 0.225 kWh between 22:19:52 and about 22:35.

**Cable reconnect.** The cable was unplugged for about 14 minutes (22:20–22:34). The server logged the drop and resumed reading on its own, with no CRC failures.
