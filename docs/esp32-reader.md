# ESP32 P1 reader: parts list and wiring

**Goal:** read the meter around the clock without the Mac. A small Wi-Fi board plugs into the P1 port and runs on the port's own 5 V supply. It keeps recording while the Mac sleeps, and the dashboard catches up when the Mac wakes.

Specs below come from the [DSMR 5.0.2 P1 standard](reference/p1/dsmr-5.0.2-p1-companion-standard.pdf), §5–6, and from what we measured on this meter (`meter.md` §3).

## Parts

| # | Part | Qty | Notes | Approx. cost |
|---|---|---|---|---|
| 1 | **ESP32 board.** On hand: a 30-pin **ESP32-WROOM-32** (CH340C, USB-C) on a pin-header expansion board ([`esp32-board.md`](esp32-board.md)) | 1 | The community builds use the same **30-pin ESP32-WROOM-32D** or a **Wemos D1 mini** (ESP8266); both are proven on IEC Kaifa meters. An **ESP32-C3 "SuperMini"** would draw less power, but the WROOM works (mp3llll runs one from P1) and has more memory for the history buffer. | on hand |
| 2 | **RJ12 6P6C cable**, **straight**, all 6 wires | 1 | Must be **6P6C**. A 6P4C (RJ11) plug has no pins 1 and 6, so it carries no power. Kept whole: one end in the meter, the other in item 3. **Straight** matters here: a reversed cable swaps pins 1↔6, 2↔5, 3↔4 and puts +5 V on a GND terminal (see the check under Wiring). | $1–3 |
| 3 | **RJ12 6P6C female jack with 6 screw terminals** | 1 | Replaces cutting the cable: no stripping, no guessing wire colours, and the cable stays reusable. The Request resistor fits straight into its terminals. | $2–5 |
| 4 | **1 kΩ resistor**, ¼ W | 2 | (a) Pull-up on the open-collector Data line to **3.3 V**, never 5 V. This gives about 3.3 mA through the meter's optocoupler, which is what klimofey and mp3llll use (yoni03 also lists 2 × 1 kΩ); 680 Ω is closer to the spec's 5 mA. Don't use 10 kΩ: too weak for clean 115200-baud edges. (b) Series resistor from +5 V to Data Request. | <$1 |
| 5 | **1000 µF electrolytic capacitor**, 10 or 16 V, low ESR | 1 | **Needed with the WROOM-32** (see Power budget); optional only on a C3. None of the community builds use one; they rely on reduced Wi-Fi power. The dev board already has its own 100 nF decoupling, so no extra ceramic is needed. | <$2 |
| 6 | **Dupont jumper wires**, male-to-female | ~4 | The expansion board has pin headers, not screw terminals: the female end goes on the ESP32 pin, the male pin into the jack's screw terminal. | $1–2 |
| 7 | Small enclosure (about 50 × 30 × 15 mm, project box or 3D print) | 1 | Must fit inside or next to the meter cabinet without stopping its door closing. | $1–3 |
| 8 | Heat-shrink tubing | — | Over the Data pull-up resistor's legs. | <$1 |

**Total still to buy: about $14** (items 2–6; see [Checked listings](#checked-listings-aliexpress-2026-11-19)).

**Optional**
- **5 V USB power supply and USB-C cable.** A fallback if the P1 supply turns out too weak (brownouts). Then leave pin 1 **unconnected** and power the board by USB, but still tie Data Request to the board's 5 V.
- **ESP32 board with an external antenna connector, plus an antenna.** Useful if Wi-Fi is weak at the meter cabinet, especially behind a metal door.

**Tools:** multimeter (required for the check below), a USB-C data cable for flashing, a small screwdriver. No soldering iron needed with the screw-terminal jack.

## Wiring

RJ12 pin numbering follows DSMR Figure 5-1. Pin numbers below are the **jack's terminal numbers**, which match the meter's pins only with a straight cable, so check them first (step 1 below).

| RJ12 pin | DSMR signal | Connect to (WROOM-32 board) |
|---|---|---|
| 1 | +5 V (250 mA max) | Board **VIN**, and the 1 kΩ to pin 2 |
| 2 | Data Request | **1 kΩ to pin 1 (+5 V)**, both legs in the jack's terminals, so the meter always sends. Never to a GPIO (3.3 V) |
| 3 | Data GND | Board **GND** |
| 4 | n.c. | Nothing |
| 5 | Data (open collector, **inverted**) | **D16 (RX2)**, plus **1 kΩ to 3V3** at the board (GPIO3/RX0 on Wemos, e.g. GPIO20 on a C3) |
| 6 | Power GND | Board **GND** |

Put the 1000 µF capacitor across **VIN and GND** right at the board, **minus stripe to GND**.

**WROOM-32 board specifics**
- Feed the P1 5 V into the dev board's **VIN** pin. Don't use the expansion board's barrel jack: it goes through its own regulator.
- Keep the expansion board's **JUMP on 3.3 V**.
- D16 is free on a WROOM module. It is only taken by PSRAM on a WROVER.

**Before plugging in the board** (from the community guides):
1. With only the cable and jack plugged into the meter, measure DC from **terminal 1 to terminal 6**. It should be about **+5 V**. If it reads about −5 V, or the 5 V shows up between other terminals, the cable is reversed (pins 1↔6, 2↔5, 3↔4): swap the cable, or relabel the terminals, before anything touches the board.
2. Cable colours differ between cables. Go by pin position, never colour.
3. **Never connect USB and the meter at the same time.** USB is for the first flash only; later updates go over Wi-Fi (OTA). The dev board may back-feed 5 V between USB and VIN.

**Signal inversion:** the P1 Data line is logically inverted. The ESP32 UART can invert RX in hardware, so no transistor is needed: ESP-IDF `uart_set_line_inverse(…, UART_SIGNAL_RXD_INV)`, or `rx_pin: {number: 20, inverted: true}` in ESPHome. Serial settings: **115200 8N1**.

## Power budget

- DSMR guarantees 250 mA continuous from P1. Its overcurrent protection trips between 260 and 300 mA and then folds back.
- An ESP32-C3 averages well under 100 mA on Wi-Fi, but transmit bursts can briefly go above the limit.
- **The WROOM-32 board on hand has less margin.** Its Wi-Fi transmit bursts are larger than a C3's. Its 1117 regulator is linear, so the 5 V side carries the full 3.3 V current. The CH340C and the red PWR LED add a constant load. Peaks can pass 250 mA, so item 5, the 1000 µF capacitor, is required rather than optional. mp3llll runs the same kind of board from P1, so it works with these settings.
- klimofey's tested ESPHome config sets `output_power: 8.5dBm` and `power_save_mode: LIGHT` for exactly this reason. Use both from the first flash.
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

> **On hand since 18 Nov 2026:** a 30-pin ESP32-WROOM-32 (CH340C, USB-C) on a pin-header expansion board, so the first two rows are covered, with Dupont wires instead of screw terminals. Details in [`esp32-board.md`](esp32-board.md). The rest is chosen in [Checked listings (2026-11-19)](#checked-listings-aliexpress-2026-11-19).

| ✓ | Item | Search for | Qty | Must have | ≈ $ |
|---|---|---|---|---|---|
| ☑ | ESP32 dev board | `ESP32 WROOM-32D 30pin USB-C CH340` | 1 | **30-pin** version, USB-C | on hand |
| ☑ | Expansion board | `ESP32 30P expansion board screw terminal` | 1 | Made for the **30-pin** board (not 38-pin) | on hand (pin headers) |
| ☐ | RJ12 cable | `RJ12 6P6C cable straight` | 1 | **6P6C** (6 wires), **straight**. Kept whole. | 1–3 |
| ☐ | RJ12 female screw-terminal jack | `RJ12 6P6C female screw terminal` | 1 | **6** terminals (6P6C), female | 2–5 |
| ☐ | Resistors | `1K ohm resistor 1/4W` or a resistor kit | 2 needed | 1 kΩ, ¼ W. A kit also gives 680 Ω. | 1–3 |
| ☐ | Capacitor | `1000uF 10V low ESR` | 1 | 1000 µF, 10 or 16 V | <2 |
| ☐ | Dupont jumpers | `dupont jumper wire` kit | ~4 | Male-to-female (kits include all three types) | 1–2 |

### Option B: klimofey's MA110M build (Wemos D1 mini; needs soldering)

| ✓ | Item | Link | Qty | ≈ $ |
|---|---|---|---|---|
| ☐ | Wemos D1 mini (USB-C, ESP8266, female headers) | [example](https://aliexpress.com/item/1005006018009983.html) | 1 | 2–4 |
| ☐ | RJ12 6P6C straight cable | [example](https://aliexpress.com/item/1005006226706163.html) | 1 | 1–3 |
| ☐ | RJ12 6P6C PCB jack with pre-crimped wires (optional) | [example](https://aliexpress.com/item/1005005654491710.html) | 1 | 1–2 |
| ☐ | Prototyping PCB, about 3 × 7 cm | [example](https://aliexpress.com/item/1005004818919331.html) | 1 | 1–2 |
| ☐ | Resistor kit (1 kΩ ¼ W) | [example](https://aliexpress.com/item/1005005855324735.html) | 2 needed | 1–3 |

### Checked listings (AliExpress, 2026-11-19)

For the WROOM-32 board on hand. Black Friday prices shown to an Israel address (sale ends Dec 3); they change often. All five are **Choice** items, so together they clear the **$12 free-shipping** minimum. Delivery estimate: Dec 2–9.

| ✓ | Item | Listing | Variant to pick | Price | Rating / sold |
|---|---|---|---|---|---|
| ☐ | **RJ12 6P6C straight cable** | [1005006226706163](https://www.aliexpress.com/item/1005006226706163.html), Usangreen Store | **1 m** | $2.95 | 4.9★, 60 reviews, 1,000+ sold. 2 reviews mention "wrong connector orientation": do the terminal 1–6 check |
| ☐ | **RJ12 6P6C female jack, 6 screw terminals** | [1005011586713300](https://www.aliexpress.com/item/1005011586713300.html), UpperFu Store | — | $4.93 | 69 sold, **no reviews yet** |
| ☐ | **Resistor kit** (incl. 1 kΩ, 680 Ω) | [1005005855324735](https://www.aliexpress.com/item/1005005855324735.html), ENLINCA PRO Store | **300 pcs set** | $2.43 | 4.9★, 185 reviews, 1,000+ sold. Values printed on the strips |
| ☐ | **Dupont jumper kit** (M-M, M-F, F-F) | [1005002000655439](https://www.aliexpress.com/item/1005002000655439.html) | **20 cm** | $2.17 | 4.9★, 10K+ sold |
| ☐ | **1000 µF low-ESR capacitor** | [1005002542855250](https://www.aliexpress.com/item/1005002542855250.html) | **1000 µF, 10 V or 16 V** | $1.42 | 4.8★, 4K+ sold |

**Total:** about $14 (cable $2.95 + jack $4.93 + resistors $2.43 + jumpers $2.17 + capacitor $1.42).

**Alternative to the jack + cable:** [1005012829819039](https://www.aliexpress.com/item/1005012829819039.html), an RJ12 **male** plug on a short lead to 6 screw terminals (0.2–5 m, from $1.87). It plugs straight into the meter, but it's not Choice: $2.95 shipping, Dec 12–20, 1 review.

**Still to check:** a multimeter, if none is on hand (not looked up; a basic one is about $5–10).

### Checked listings (AliExpress, 2026-11-14)

_Superseded by the 2026-11-19 list above: written before the ESP32 board arrived._

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
- **ESP32-WROOM-32 board and expansion board:** on hand since 18 Nov 2026.
- **FTDI P1 cable:** already owned. Keep it for testing and for the Mac dashboard. It can't feed the ESP32: both its USB end and the board's USB-C are USB *devices*, and the WROOM-32 has no USB host.
- **USB-C data cable:** on hand (used to flash the board on 18 Nov). For the first flash only.
- **Multimeter:** required for the terminal 1–6 check before connecting.
- **Soldering iron:** not needed with the screw-terminal jack.
- **Enclosure:** optional; yoni03 links a 3D-printable one on MakerWorld.

**Totals:** this build (WROOM-32 on hand) ≈ $14 with free shipping; Option B ≈ $6–14, before shipping.

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
