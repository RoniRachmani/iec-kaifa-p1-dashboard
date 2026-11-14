# ESP32 P1 reader: parts list and wiring

**Goal:** read the meter around the clock without the Mac. A small Wi-Fi board plugs into the P1 port and runs on the port's own 5 V supply. It keeps recording while the Mac sleeps, and the dashboard catches up when the Mac wakes.

Specs below come from the DSMR 5.0.2 P1 standard (`reference/dsmr-5.0.2-p1-companion-standard.pdf`, §5–6) and from what we measured on this meter (`METER.md` §3).

## Parts

| # | Part | Qty | Notes | Approx. cost |
|---|---|---|---|---|
| 1 | **ESP32-C3 "SuperMini"** board (USB-C, onboard 3.3 V regulator) | 1 | Small, low power, and its 5 V pin accepts the P1 supply. The community builds use a **30-pin ESP32-WROOM-32D** (optionally on a screw-terminal breakout, so no soldering) or a **Wemos D1 mini** (ESP8266). Both are proven on IEC Kaifa meters. The ESP32 has more memory for the history buffer. | $3–6 |
| 2 | **RJ12 6P6C cable**, straight, all 6 wires | 1 | Must be **6P6C**. A 6P4C (RJ11) plug has no pins 1 and 6, so it carries no power. Cut one end off and solder to the board. Alternatively, an RJ12 breakout board plus a short patch cable. | $1–3 |
| 3 | **1 kΩ resistor**, ¼ W | 2 | (a) Pull-up on the open-collector Data line to **3.3 V**, never 5 V. This gives about 3.3 mA through the meter's optocoupler, which is what klimofey and mp3llll use (yoni03 also lists 2 × 1 kΩ); 680 Ω is closer to the spec's 5 mA. Don't use 10 kΩ: too weak for clean 115200-baud edges. (b) Series resistor from +5 V to Data Request. | <$1 |
| 4 | 470–1000 µF / 10 V electrolytic + 100 nF ceramic capacitor | 1 each | **Optional extra margin.** None of the community builds use them; they rely on reduced Wi-Fi power instead (see Power below). Fit them if the board resets. | <$1 |
| 6 | Small enclosure (about 50 × 30 × 15 mm, project box or 3D print) | 1 | Must fit inside or next to the meter cabinet without stopping its door closing. | $1–3 |
| 7 | Heat-shrink tubing, a little perfboard or hookup wire | — | | <$1 |

**Total: about $8–15.**

**Optional**
- **5 V USB power supply and USB-C cable.** A fallback if the P1 supply turns out too weak (brownouts). Then leave pin 1 **unconnected** and power the board by USB, but still tie Data Request to the board's 5 V.
- **ESP32 board with an external antenna connector, plus an antenna.** Useful if Wi-Fi is weak at the meter cabinet, especially behind a metal door.

**Tools:** soldering iron, multimeter, and a USB-C data cable for flashing.

## Wiring

RJ12 pin numbering follows DSMR Figure 5-1. **Check with a multimeter before connecting the board:** with the plug in the meter, pin 1 to pin 6 should read about 5 V.

| RJ12 pin | DSMR signal | Connect to |
|---|---|---|
| 1 | +5 V (250 mA max) | Board **5V**, and to pin 2 |
| 2 | Data Request | **1 kΩ to pin 1 (+5 V)**, so the meter always sends. Never to a GPIO (3.3 V) |
| 3 | Data GND | Board **GND** |
| 4 | n.c. | Nothing |
| 5 | Data (open collector, **inverted**) | Board **RX GPIO** (GPIO16/RX2 on ESP32-WROOM, GPIO3/RX0 on Wemos, e.g. GPIO20 on a C3), plus **1 kΩ to 3V3** |
| 6 | Power GND | Board **GND** |

If you fit the optional capacitors, put them across 5V and GND right at the board.

**Before plugging in the board** (from the community guides):
1. With only the cable plugged into the meter, measure DC between the 5V wire and GND. It should be about **+5 V**. If it reads negative, the wiring is reversed; fix it first.
2. Cable colours differ between cables. Go by pin position, never colour.
3. **Never connect USB and the meter at the same time.** USB is for the first flash only; later updates go over Wi-Fi (OTA).

**Signal inversion:** the P1 Data line is logically inverted. The ESP32 UART can invert RX in hardware, so no transistor is needed: ESP-IDF `uart_set_line_inverse(…, UART_SIGNAL_RXD_INV)`, or `rx_pin: {number: 20, inverted: true}` in ESPHome. Serial settings: **115200 8N1**.

## Power budget

- DSMR guarantees 250 mA continuous from P1. Its overcurrent protection trips between 260 and 300 mA and then folds back.
- An ESP32-C3 averages well under 100 mA on Wi-Fi, but transmit bursts can briefly go above the limit. That is why item 4, the large capacitor, matters.
- klimofey's tested ESPHome config sets `output_power: 8.5dBm` and `power_save_mode: LIGHT` for exactly this reason. Start with those.
- If the board still resets:
  1. Lower the Wi-Fi transmit power further.
  2. Enable Wi-Fi modem sleep.
  3. Switch to USB power (see Optional).
- Power drawn from P1 is **not billed**. DSMR §5.3 says it is not counted in the kWh registers.

## Firmware plan (to be written)

1. Read telegrams at 115200 baud with inverted RX, and verify the CRC16 (same check as `server.py`).
2. Keep the latest telegram, and serve it over Wi-Fi as raw text, so `server.py` can read from the network instead of `/dev/cu.usbserial*`.
3. Every minute, save a snapshot of the three import counters (`1.8.11–13`) and the active tariff into a ring buffer in flash.
   - About 16 bytes per row. 30 days ≈ 43,000 rows ≈ 0.7 MB, which fits in the 4 MB flash.
4. Add a `/history?since=` endpoint. When the Mac wakes, `server.py` backfills the gap from it, so the plan comparison and hourly charts have no holes.
5. Synchronise the clock by NTP. The meter's own clock (`0-0:1.0.0`) is a fallback.

Changes needed in `server.py`:
- a network source (`--source tcp://host:port`)
- the backfill call on startup and on reconnect

## AliExpress shopping list

Prices are rough AliExpress ranges, not checked. The links are the ones klimofey's README lists as examples; I haven't checked that they are still live. Any listing with the same specs works.

### Option A: ESP32 on a screw-terminal board (recommended; no soldering except the cable)

| ✓ | Item | Search for | Qty | Must have | ≈ $ |
|---|---|---|---|---|---|
| ☐ | ESP32 dev board | `ESP32 WROOM-32D 30pin USB-C CH340` | 1 (buy 2, cheap spare) | **30-pin** version, USB-C | 3–5 each |
| ☐ | Screw-terminal expansion board | `ESP32 30P expansion board screw terminal` | 1 | Made for the **30-pin** board (not 38-pin) | 1–3 |
| ☐ | RJ12 cable | `RJ12 6P6C cable straight` ([example](https://aliexpress.com/item/1005006226706163.html)) | 1 | **6P6C** (6 wires), straight. Cut one end off for the screw terminals. | 1–3 |
| ☐ | Or: RJ12 plug with loose crimped wires | `RJ12 6P6C crimped wires` ([example](https://aliexpress.com/item/1005007821256603.html)) | 1 | 6 wires; skips cutting and stripping | 1–3 |
| ☐ | Resistors | `1K ohm resistor 1/4W` or a resistor kit ([example](https://aliexpress.com/item/1005005855324735.html)) | 2 needed | 1 kΩ, ¼ W. A kit also gives 680 Ω. | 1–3 |
| ☐ | Optional: capacitors | `470uF 10V electrolytic` + `100nF ceramic` | 1 each | Only if the board resets | <1 |

### Option B: klimofey's MA110M build (Wemos D1 mini; needs soldering)

| ✓ | Item | Link | Qty | ≈ $ |
|---|---|---|---|---|
| ☐ | Wemos D1 mini (USB-C, ESP8266, female headers) | [example](https://aliexpress.com/item/1005006018009983.html) | 1 | 2–4 |
| ☐ | RJ12 6P6C straight cable | [example](https://aliexpress.com/item/1005006226706163.html) | 1 | 1–3 |
| ☐ | RJ12 6P6C PCB jack with pre-crimped wires (optional) | [example](https://aliexpress.com/item/1005005654491710.html) | 1 | 1–2 |
| ☐ | Prototyping PCB, about 3 × 7 cm | [example](https://aliexpress.com/item/1005004818919331.html) | 1 | 1–2 |
| ☐ | Resistor kit (1 kΩ ¼ W) | [example](https://aliexpress.com/item/1005005855324735.html) | 2 needed | 1–3 |

### Checked listings (AliExpress, 2026-11-14)

Prices are 11.11-sale prices shown to an Israel address, before shipping; they change often. Delivery estimate for the Choice items: Nov 27 – Dec 2.

| ✓ | Item | Listing | Variant to pick | Price | Rating / sold |
|---|---|---|---|---|---|
| ☐ | **ESP32 + screw-terminal board (set)** | [1005006490116433](https://www.aliexpress.com/item/1005006490116433.html), BodyWell Store, Choice | **"one set"** (board + breakout) | $7.49 (board only $5.36, breakout only $4.25) | 4.8★, 353 reviews, 5,000+ sold |
| ☐ | **RJ12 6P6C straight cable** | [1005006226706163](https://www.aliexpress.com/item/1005006226706163.html) (klimofey's link) | **1 m** (also 0.5–10 m) | from $2.99 | 63 reviews, 1,000+ sold |
| ☐ | **1 kΩ resistors** (kit) | [1005005855324735](https://www.aliexpress.com/item/1005005855324735.html) (klimofey's link) | 300 pcs set (30 values incl. 1 kΩ, 680 Ω) | from $2.41 | 185 reviews, 1,000+ sold |
| ☐ | Optional: RJ12 jack with wires | [1005005654491710](https://www.aliexpress.com/item/1005005654491710.html) (klimofey's link) | **623K 6×150 mm** (6-wire; not the 4-wire 623K) | $1.47 / 5 pcs | 75 reviews, 800+ sold |
| ☐ | Alt: RJ12 cable with loose wires | [1005007821256603](https://www.aliexpress.com/item/1005007821256603.html) (klimofey's link) | **RJ12 6P6C**, 1 M | from $2.40 | 10 reviews, 108 sold; slower delivery (Dec 7–14) |
| ☐ | Option B board: Wemos D1 mini | [1005006018009983](https://www.aliexpress.com/item/1005006018009983.html) (klimofey's link) | **D1 MINI TYPE-C** | from $2.59 | 69 reviews, 1,000+ sold |

**Option A total:** about $13 (set $7.49 + cable $2.99 + resistor kit $2.41).

**Notes**
- **Pin count:** the set's photos show the 30-pin layout, but no variant is labelled "30-pin". Check the board in the photos before ordering.
- **Avoid** [1005004685935016](https://www.aliexpress.com/item/1005004685935016.html) ("ESP32-DevKitC … ExpansionBoard", $3.66). Its photos show the longer **38-pin** DevKitC, and it comes without the terminal board.
- **Dead link:** klimofey's prototyping-PCB link (1005004818919331) no longer shows a normal listing. It's only needed for Option B; any 3×7 cm perfboard works.

### Already have or don't need
- **FTDI P1 cable:** already owned. Keep it for testing and for the Mac dashboard.
- **USB-C data cable:** for the first flash only (not a charge-only cable).
- **Multimeter:** needed for the +5 V and polarity check before connecting.
- **Enclosure:** optional; yoni03 links a 3D-printable one on MakerWorld.

**Totals:** Option A ≈ $6–15, Option B ≈ $6–14, before shipping.

## Community projects checked (2026-11-14)

All three are MIT-licensed and target IEC's Kaifa meters. klimofey and mp3llll document the same wiring (yoni03's parts list matches: 6P6C cable, 2 × 1 kΩ, powered by the meter): RJ12 **6P6C** cable, P1 +5 V powering the board, **1 kΩ** Request pull-up to +5 V, **1 kΩ** Data pull-up to 3.3 V, and UART **115200 8N1 with RX inverted in software**. No transistor or capacitor in any of them.

| Project | Board | Data pin | Firmware | Status |
|---|---|---|---|---|
| [klimofey/iec-p1-esphome](https://github.com/klimofey/iec-p1-esphome) | Wemos D1 mini (ESP8266) | GPIO3 / RX0 (UART logging disabled) | ESPHome `dsmr:` with CRC check; `rx_buffer_size: 1700`; Wi-Fi 8.5 dBm, light sleep | Built for the **MA110M** (your model). Author: "1 kΩ works reliably". 680 Ω suggested for spec-level current. |
| [mp3llll/iec-p1-esphome-3phase](https://github.com/mp3llll/iec-p1-esphome-3phase) | ESP32-WROOM-32D, 30-pin, terminal board | GPIO16 / RX2 | ESPHome (ESP-IDF) with a **custom CRC-checking parser**, because "the dsmr component does not know the Israeli 1.8.11–13 codes" | Built and installed on an **MA309M** (3-phase). Has pin and colour photos. |
| [yoni03/iec-PlatformIO-3phase](https://github.com/yoni03/iec-PlatformIO-3phase) | ESP32-WROOM-32D, 30-pin, CH340, terminal board | (in the guide's wiring image) | PlatformIO firmware with a **built-in web UI, history and costs**, unit tests and a 400-day simulation | The README says it is **not yet tested on a real meter**. Closest to the "logs without the Mac" goal. |

**What this means for this build**
1. Use the proven wiring above.
2. Firmware choice:
   - For Home Assistant: start from mp3llll's ESPHome parser.
   - For a standalone logger: start from yoni03's firmware.
   - Writing our own is only needed for the backfill endpoint for `server.py`.
3. The two sources conflict on whether ESPHome's stock `dsmr:` component reads `1.8.11–13`. Check the logs on the first boot.

## Alternative without soldering

A **Raspberry Pi Zero 2 W** with the existing FTDI cable can run `server.py` unchanged; only the serial auto-detect needs `/dev/ttyUSB*` added. It needs a mains USB power supply near the meter, a microSD card, and it costs more (about $20–30). The ESP32 runs from the meter itself and needs no power socket.

## Safety

- The P1 port is opto-isolated from the mains and read-only (DSMR §5.2, §5.5). Nothing on it can affect the meter or the billing.
- Only open the **unsealed P1 flap**. Never touch the sealed covers or the Test button.
- Don't route the cable through the sealed parts of the cabinet.
