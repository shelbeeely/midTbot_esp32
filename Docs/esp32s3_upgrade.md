# ESP32-S3 controller from off-the-shelf parts (2026)

The original midTbot controller is a custom PCB (V1/V2 in [`PCB/`](../PCB))
carrying a classic ESP32 DevKit, two A4988 StepSticks, an SD socket and the two
limit switches. That kit is no longer sold. This page rebuilds the controller
with an **ESP32-S3** and parts you can buy today, running
[FluidNC](https://github.com/bdring/FluidNC) 4.x, the successor to the
Grbl_ESP32 firmware the midTbot originally used. FluidNC 4.0 (January 2026) is
the first release with ESP32-S3 support. Use 4.0.1 or newer.

What changes:

* **Electronics**: modules wired together, no custom PCB to order.
* **Controller plate**: the V2 PCB was structural (the motors bolt through it
  and the limit switches are soldered to it). A printed plate with the same
  outline, motor cutouts, screw holes and switch footprints takes its place:
  [`STL/midt_esp32s3_controller_plate.stl`](../STL/midt_esp32s3_controller_plate.stl),
  generated from the V2 Gerbers by
  [`Tools/controller_plate/make_plate.py`](../Tools/controller_plate/make_plate.py).
* **Enclosure**: the stock cover leaves about 22 mm above the board, and the
  20 mm motors use nearly all of it. The modules don't fit under it, so they
  go in a small box next to the plotter, with one cable bundle to the motors,
  servo and switches.

Everything mechanical in [mechanical_BOM.md](mechanical_BOM.md) stays the same.

## Parts

| Part | Qty | Notes |
|---|---|---|
| Espressif **ESP32-S3-DevKitC-1-N16R8** | 1 | N8R8 or N8 also work. Digi-Key, Mouser, Adafruit, Amazon. Buy the genuine Espressif board, or a clone with the identical 2 x 22 pinout. |
| **TMC2209 StepStick** driver | 2 | BIGTREETECH TMC2209 V1.3, FYSETC, MKS, or any with 0.11 ohm sense resistors. Used in standalone step/dir mode. Much quieter than the A4988 at night. |
| StepStick **driver expansion board** | 2 | The generic "A4988/DRV8825 stepper driver expansion board": socket, motor screw terminal, VMOT capacitor, M0/M1/M2 DIP switches. |
| **5 V buck regulator**, 2.5 A or more | 1 | Pololu D24V22F5 (5 V 2.5 A) or D36V28F5 (5 V 3.2 A). A generic MP1584/LM2596 module set to 5.0 V also works. Powers the S3 board and the servo. |
| **microSD breakout**, 3.3 V | 1 | Adafruit 4682 ("Micro SD SPI or SDIO Card Breakout - 3V ONLY"). Holds the journal-page G-code files. |
| Omron **D2FS-FL-N-A** micro switch | 2 | Same limit switches as the V2 board. They mount in their footprints on the printed plate. |
| 12 V 3 A power supply | 1 | Same as the stock build. |
| DC barrel jack to screw terminal adapter | 1 | Matches the supply's 5.5 x 2.1 mm plug. |
| 470 uF 16 V electrolytic capacitor | 1 | Across the servo's 5 V and GND, to absorb current spikes. |
| MG90S micro servo | 1 | As stock. For pen pressure add the spring from [journal_pages.md](journal_pages.md). |
| Wiring | - | Dupont jumpers (female-female), 22-26 AWG hookup wire, 4-wire stepper extension cables, 3-wire servo extension. |
| Project box, roughly 120 x 80 x 40 mm | 1 | Any plastic box, or print one. |
| Printed **controller plate** | 1 | PETG or PLA, 1.6 mm thick (keeps screw and pulley heights), 100 % infill. |

## Pin map

All signals are on the DevKitC-1's **J1** header (the row that starts 3V3,
3V3, RST). None of them are strapping, USB, UART0, flash/PSRAM (GPIO35-37) or
RGB LED (GPIO38/48) pins.

| J1 pin | GPIO | Function | Goes to |
|---|---|---|---|
| 1 | 3V3 | 3.3 V out | Both driver boards' logic supply (VDD), SD breakout 3V |
| 4 | 4 | X step | Driver board 1 STEP |
| 5 | 5 | X dir | Driver board 1 DIR |
| 6 | 6 | Y step | Driver board 2 STEP |
| 7 | 7 | Y dir | Driver board 2 DIR |
| 8 | 15 | Stepper enable (shared) | EN on both driver boards |
| 9 | 16 | Servo PWM | Servo signal (orange) |
| 10 | 17 | X limit | X switch (other leg to GND) |
| 11 | 18 | Y limit | Y switch (other leg to GND) |
| 16 | 10 | SD CS | SD breakout CS |
| 17 | 11 | SD MOSI | SD breakout SI |
| 18 | 12 | SD SCK | SD breakout CLK |
| 19 | 13 | SD MISO | SD breakout SO |
| 21 | 5V | 5 V in | Buck regulator 5 V out |
| 22 | G | Ground | Common ground |

GPIO 8 and 14 are kept for the [multipen](multipen.md) colour-selector
servos (J1 pins 12 and 20), GPIO 9 for optional SD card detect, and GPIO 46
is a strapping pin, so avoid it. The firmware config with these pins is
[`Firmware/FluidNC/midtbot_s3.yaml`](../Firmware/FluidNC/midtbot_s3.yaml)
([`midtbot_s3_multipen.yaml`](../Firmware/FluidNC/midtbot_s3_multipen.yaml)
adds the selector servos).

The V2 board used GPIO 12/26 (X step/dir), 14/25 (Y step/dir), 13 (enable),
27 (servo), 2 and 4 (limits), and 5/18/19/23 (SD). GPIO 22-25 don't exist on
the S3 and 26-32 are its flash pins, which is why the map changed.

## Wiring

**Power**

```
12 V supply -> barrel jack adapter -+-> driver board 1 VMOT / GND
                                    +-> driver board 2 VMOT / GND
                                    +-> buck regulator IN / GND
buck 5 V OUT -+-> DevKitC-1 J1 pin 21 (5V)
              +-> servo red (5 V), with the 470 uF capacitor across red/brown
all grounds joined: supply GND, buck GND, driver GNDs, DevKitC-1 GND, servo brown, SD GND
```

* **USB and the 5V pin must not be powered at the same time.** Espressif
  lists the board's power inputs (USB, the 5V pin, the 3V3 pin) as mutually
  exclusive. Once the board is fed from the buck regulator, either unplug the
  12 V supply before plugging in USB, or use a USB data-only adapter (a "USB
  power blocker"). Day to day you won't need USB: FluidNC runs a WiFi web UI
  for uploading and running files.
* Use the port labeled **UART** for flashing and the serial console.

**Drivers** (each TMC2209 on its expansion board)

* **Logic supply from 3.3 V, not 5 V.** The expansion board's logic pin
  (often labeled 5V or VDD) goes to J1 pin 1 (3V3). Powered at 5 V, a TMC2209
  won't reliably see the S3's 3.3 V step pulses as high. Check that the
  board has no regulator on that pin (the common ones don't).
* **Microstepping 1/16**: DIP switches M0 (MS1) and M1 (MS2) **on**, M2
  **off**. That matches `steps_per_mm: 100` in the config.
* **Motor current**: NEMA14 motors in the stock BOM are rated 0.4 A. Set
  about 0.3-0.35 A RMS. For 0.11 ohm TMC2209 StepSticks, Vref ~= 1.41 x I_rms,
  so **Vref ~= 0.45-0.5 V** measured between the trim pot and GND, with 12 V
  on and the motor connected. Check your driver's own documentation if it
  uses different sense resistors.
* Motor coil pairs go to the 1A/1B and 2A/2B terminals. Never unplug a motor
  with power on.

**Limit switches**

* Fit both D2FS switches into their footprints on the printed plate, on the
  same side as on the V2 board (underneath). Their pins poke through the
  plate. Solder two wires to each: COM, plus the contact that **closes when
  the lever is pressed** (check with a multimeter).
* One wire to GND, the other to GPIO17 (X) or GPIO18 (Y). The config uses
  the internal pull-ups and treats "pulled to GND" as triggered.

**SD card**: 3V, GND, CLK, SO, SI and CS as in the pin map. DET can go to
GPIO9 if you want card detection (set `card_detect_pin: gpio.9`).

## Assembly with the printed plate

1. Print [`STL/midt_esp32s3_controller_plate.stl`](../STL/midt_esp32s3_controller_plate.stl)
   flat, 1.6 mm thick. To change thickness or hole size, regenerate it:
   `pip install shapely trimesh mapbox_earcut`, then
   `python3 Tools/controller_plate/make_plate.py --thickness 1.6 --hole-comp 0.2`
   (`--hole-comp` enlarges every hole to make up for printed holes coming out
   small).
2. Assemble exactly as with the V2 PCB: the motors bolt through the plate with
   the same M3 x 16 screws, and the plate mounts with the same screws as the
   board did.
3. Run the motor, servo and switch cables out through the cover's openings to
   the electronics box. Leave enough slack that nothing tugs on the moving
   head.

## Firmware

1. Flash **FluidNC 4.0.1 or newer** with its web installer (choose the
   ESP32-S3 build) or the release's `install-wifi_s3` script, with the 12 V
   supply **off** and USB on the UART port.
2. Connect to the FluidNC WiFi access point and open its web UI, or use
   FluidTerm over USB.
3. Upload [`Firmware/FluidNC/midtbot_s3.yaml`](../Firmware/FluidNC/midtbot_s3.yaml)
   and make it the active config (`$Config/Filename=midtbot_s3.yaml`), then
   restart.
4. First checks, still without paper:
   * `?` shows the status. Press each limit switch by hand: `Pn:X` / `Pn:Y`
     should appear. If a switch reads triggered when released, remove `:low`
     from its pin in the config.
   * Jog Z between 5 and -2 and confirm the servo moves the right way. Swap
     `min_pulse_us`/`max_pulse_us` if not.
   * `$H` to home. If an axis runs away from its switch, flip that axis's
     `positive_direction`.
   * Jog X and Y. If the motion comes out diagonal or mirrored, swap the X
     and Y step/dir pins, or flip one motor's connector, until X and Y move
     straight.
   * Draw a 50 mm square and adjust `steps_per_mm` if it's off. Measure the
     usable travel and set `max_travel_mm` for X and Y. Keep `max_x`/`max_y`
     in your `journal_plot` profile in step with them.
5. Then fit the pressure spring and calibrate: [journal_pages.md](journal_pages.md).

## Other off-the-shelf options

* **Single-board ESP32-S3 controllers for FluidNC** exist, e.g. the
  [PiBot V5.88 Ultra](https://www.pibot.com/pibot-fluidnc-grblhal-esp32-s3-6-1-axis-cnc-controller-v5-88-ultra)
  (ESP32-S3, plug-in drivers) and Bart Dring's
  [Doberman](https://www.elecrow.com/doberman-esp32-s3-8-axis-cnc-controller.html)
  (ESP32-S3, external drivers). Both are far larger than the midTbot needs
  and use their own pin maps. Keep the `z:` servo section and `kinematics:`
  from `midtbot_s3.yaml` and take the pins from the vendor's config.
* **Not S3, but the least wiring**: a 2-axis FluidNC pen/laser board with
  built-in TMC2209s and a servo header, such as the
  [Elecrow TMC2209 Pen/Laser controller V2.2](https://www.elecrow.com/tmc2209-pen-laser-fluidnc-cnc-controller.html)
  (classic ESP32). The pressure setup and `journal_plot` work the same.
