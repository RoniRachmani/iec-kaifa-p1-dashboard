# ESP32 board: everything we know

_Started 18 Nov 2026 from a photo of the board, the macOS USB registry, esptool and espefuse readouts, and a full read of its 4 MB flash. §4–5 describe the board as it arrived; it has since been updated to AT v4.1.1.0 (§7). It was a gift and is the intended board for the standalone reader in [`ESP32-READER.md`](ESP32-READER.md)._

## Summary

- **Board:** 30-pin **ESP32-WROOM-32** dev board (USB-C, **CH340C** USB-serial), seated on a **pin-header expansion board** with its own power inputs. This covers Option A's "ESP32 dev board" and "expansion board" items, but with pin headers instead of screw terminals.
- **Chip:** genuine **ESP32-D0WD-V3, revision v3.1**, dual core, 240 MHz, 40 MHz crystal, 4 MB flash.
- **Security:** **no eFuse locks set.** No flash encryption, no secure boot, JTAG and UART download enabled. It can be reflashed freely.
- **Firmware now:** Espressif's stock **ESP32-AT v4.1.1.0**, flashed 18 Nov 2026 (§7). It shipped with **v2.4.0.0** (20 May 2022), never configured and never updated (§4–5); a full backup of that is kept.
- **Serial port on the Mac:** `/dev/cu.usbserial-110`. The dashboard's auto-detect skips it because it isn't an FTDI chip.

---

## 1. Hardware: from the photo

**Dev board (top)**

| Item | Value |
|---|---|
| Module | **ESP-WROOM-32** in a metal can, FCC ID `2AC7Z-ESPWROOM32`, PCB antenna |
| USB | **USB-C** (data and power) |
| USB-serial chip | **WCH CH340C** (SOIC-16, built-in crystal) |
| Regulator | 1117-series, 3.3 V (SOT-223) |
| Buttons | **BOOT** (GPIO0) and **EN** (reset) |
| LEDs | **PWR** (red), **D2** (on GPIO2) |
| Header pins (left) | 3V3, GND, D15, D2, D4, **D16 (RX2)**, D17 (TX2), D5, D18, D19, D21, RX0, TX0, D22, D23 |
| Header pins (right) | VIN, GND, D13, D12, D14, D27, D26, D25, D33, D32, D35, D34, VN, VP, EN |

**Expansion board (bottom)**

| Item | Value |
|---|---|
| Power inputs | **DC barrel jack 6.5–16 V**, micro-USB, USB-C (`USB5V`). These are power only; data goes through the dev board's own USB-C |
| Power parts | SS24 Schottky diode, a 1117-series regulator (marked `1117 50`, probably 5 V for the barrel jack), electrolytic capacitor |
| Indicator | Power LED (`PWR-LED`) |
| GPIO headers | One **GND / VCC / signal** triplet per pin (male pins), labelled with the dev board's pin names |
| **JUMP** (yellow jumper) | Sets the **VCC pin of every triplet** to **3.3 V or 5 V** |
| Power block (right) | Separate **5V**, **3.3V** and **GND** pins |

**Notes for the P1 build**
- **No screw terminals.** Connect the RJ12 wires with female Dupont jumpers or crimped Dupont housings. The two 1 kΩ resistors can sit inline.
- **Keep the jumper on 3.3 V.** It only affects the triplets' VCC pins; with 3.3 V there, nothing on those rows can put 5 V on a GPIO.
- **Input-only pins:** D34, D35, VP (GPIO36) and VN (GPIO39) have no pull-ups and can't output.
- **Strapping pins:** avoid GPIO0, 2, 5, 12 and 15 for the P1 data line. They're read at reset, and **GPIO12 high at boot sets the flash to 1.8 V**, which stops the board from booting.

## 2. USB and macOS

| Item | Value |
|---|---|
| USB IDs | Vendor **0x1a86** (WCH, 6790 decimal), product **0x7523** (CH340), bcdDevice 0x0264 |
| USB product / serial | `USB Serial` / **none** (so macOS names the port after its USB location) |
| Speed | USB Full Speed (12 Mbit/s) |
| macOS driver | Apple's built-in **DriverKit AppleUSBCHCOM** (`com.apple.DriverKit-AppleUSBCHCOM`); **nothing installed** |
| Device node | **`/dev/cu.usbserial-110`** (the number changes with the USB port used) |
| USB class | Serial only: no disk, no keyboard (HID) |
| Dashboard | `server.py` auto-detect skips it (vendor isn't FTDI `0403`) and logs one line naming `--port` as the override |

## 3. Chip and eFuses (`esptool`, `espefuse`)

| Item | Value |
|---|---|
| Chip | **ESP32-D0WD-V3**, revision **v3.1** (wafer major 3), package 1 |
| Features | Wi-Fi, Bluetooth, dual core, 240 MHz, Vref calibration in eFuse, coding scheme None |
| Crystal | 40 MHz |
| MAC | **d8:13:2a:xx:xx:xx**. `d8:13:2a` is an Espressif prefix, first registered 23 Aug 2023, so the chip was made after mid-2023 and the factory flashed an older AT release |
| ROM | `ets Jul 29 2019 12:21:46` |
| Flash chip | Maker **0x68** (Boya), device **0x4016**, **4 MB**, DIO at 40 MHz, 3.3 V (set by strapping pin) |
| Flash encryption | **Off** (`FLASH_CRYPT_CNT` = 0) |
| Secure boot | **Off** (`ABS_DONE_0` and `ABS_DONE_1` = 0) |
| JTAG | Enabled (`JTAG_DISABLE` = 0) |
| UART download | Enabled (`UART_DOWNLOAD_DIS` = 0) |
| Key blocks 1–3 | All zero; no write or read protection |
| `CONSOLE_DEBUG_DISABLE` | Set; Espressif sets this at the factory on every chip |

## 4. Flash layout (as shipped; v4.1.1.0 uses the same partitions)

Partition table at `0x8000`, read from flash and matching the boot log.

| Partition | Offset | Size | Contents |
|---|---|---|---|
| (bootloader) | `0x1000` | 28 KB | ESP-IDF 2nd-stage bootloader, checksum and SHA-256 valid |
| `phy_init` | `0xF000` | 4 KB | RF calibration data |
| `otadata` | `0x10000` | 8 KB | Boot slot = `ota_0` (sequence 1); never updated over the air |
| `nvs` | `0x12000` | 56 KB | Settings (see §5) |
| `at_customize` | `0x20000` | 896 KB | AT factory parameters and sample certificates (see §5) |
| `ota_0` | `0x100000` | 1.5 MB | The esp-at app (1.38 MB used), checksum and SHA-256 valid |
| `ota_1` | `0x280000` | 1.5 MB | **Blank** |

No data anywhere outside these partitions: `0x0–0x1000` and the gap `0x9000–0xF000` are erased.

## 5. Firmware as shipped

| Item | Value |
|---|---|
| Project | Espressif **esp-at**, release **v2.4.0.0** (build 20 May 2022 = the release date) |
| Version string | `v2.3.0.0_esp32c3-142-g5641e0a-d` (the dev branch the release was cut from) |
| ESP-IDF | `qa-test-v4.3.3-20220423` |
| Boot output | `module_name:WROOM-32`, `max tx power=78`, `2.4.0` on UART0 (USB) at 115200 |
| **AT command port** | **UART1: TX GPIO17, RX GPIO16, CTS GPIO15, RTS GPIO14**, 115200. That's why `AT` gets no reply over USB |
| Factory params | `PLATFORM_ESP32`, `WROOM-32`, max TX power 78 (19.5 dBm), country `CN`, channels 1–13 |
| NVS keys | Radio calibration, AT UART settings (115200), soft-AP channel, one Espressif flag. **No Wi-Fi station SSID or password** |
| Certificates | Espressif's **public sample** certificates and keys (`ESP Root CA S1/C1/C2`, `ESPRESSIF AT`), not anyone's real credentials |
| Empty | WPA2-Enterprise certificate slots, the 576 KB `fatfs` area |

## 6. Working with it

**Serial speed:** full-flash reads at **921600** and **460800** baud failed with corrupt data on this CH340. **115200 works** (4 MB in 6 min 15 s). If a flash write fails, retry with `-b 115200`.

**Read-only checks**
```sh
esptool -p /dev/cu.usbserial-110 flash-id
espefuse -p /dev/cu.usbserial-110 summary
```

**Backup of the shipped firmware:** a full 4 MB dump taken on 18 Nov 2026, kept outside this repo as `~/Documents/ESP32-backup/esp32-wroom32-at-v2.4.0.0-factory-2026-11-18.bin`. SHA-256: `b7f680552d97606cde2141a3f014d592ee59720da6e21189768f168ac3f34b4e`. To restore it:
```sh
esptool -p /dev/cu.usbserial-110 -b 115200 write-flash 0 ~/Documents/ESP32-backup/esp32-wroom32-at-v2.4.0.0-factory-2026-11-18.bin
```

**Before flashing:** nothing else may hold the port. `server.py` no longer takes this board by auto-detect, but stop it if you've started it with `--port` pointing here. Check with `lsof /dev/cu.usbserial-110`.

**Stock firmware updates** (checked 18 Nov 2026, [espressif/esp-at releases](https://github.com/espressif/esp-at/releases)): ESP32-AT **v4.2.0.0** (17 Aug 2026) is the newest, but only through Espressif's [request form](https://www.espressif.com/en/contact-us/at-firmware-application?chip=ESP32&type=ESP32-WROOM-32&version=v4.2.0.0): the release has no assets and `dl.espressif.com` returns 404 for it. **v4.1.1.0** (1 Aug 2025) is the newest direct download. None of this matters for the P1 reader, which replaces the AT firmware entirely.

## 7. Current firmware: ESP32-AT v4.1.1.0 (flashed 18 Nov 2026)

| Item | Value |
|---|---|
| Source | [ESP32-WROOM-32-AT-V4.1.1.0.zip](https://dl.espressif.com/esp-at/firmwares/esp32/ESP32-WROOM-32/ESP32-WROOM-32-AT-V4.1.1.0.zip) from Espressif's server (27.7 MB). SHA-256 `c1482d37f7378612b5b0c2fbc161e1b492ddc5f90c25009a0adec98519d60507`. Espressif publishes no checksum, so this is what we downloaded, not a published value |
| Image written | `factory/factory_WROOM-32.bin`, full 4 MB at `0x0`: erases the old settings and both app slots |
| Command | `esptool --chip esp32 -p /dev/cu.usbserial-110 -b 115200 write-flash --flash-mode dio --flash-freq 40m --flash-size 4MB 0x0 factory_WROOM-32.bin` (96 s, hash verified) |
| Bootloader | ESP-IDF v5.4.1, compiled 1 Aug 2025; checksum and SHA-256 valid. Logs `Unicore bootloader` as a warning, which is normal |
| App | `esp-at` **v4.1.1.0**, ESP-IDF v5.4.1, compiled 1 Aug 2025; checksum and SHA-256 valid |
| Partitions | Same six as §4 |
| Boot output | `AT cmd port:uart1 tx:17 rx:16 cts:15 rts:14 baudrate:115200`, `module_name: WROOM-32`, `max tx power=78`, `v4.1.1.0` |
| Check | The partition table and app header read back from the board match the image file |
