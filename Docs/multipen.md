# Multipen: several colours in one pen

A multipen is one pen body with several colour refills, such as a BIC
4-Colour, uni Jetstream 4&1, Zebra Sarasa Multi, or Pilot Hi-Tec-C Coleto.
Pushing a colour's slider down brings that refill out and retracts the one
that was out. With a small selector on the pen mount, the midTbot can switch
colours mid-page by itself. A journal entry can have black text, a red
reminder and a blue sketch, with no pauses to swap pens.

Everything else carries over from [journal_pages.md](journal_pages.md),
including the pressure control: the existing lift servo still lifts the pen
and sets pressure for whichever refill is out.

## How it works

```
Z servo (existing)   lifts the pen, sets pressure       +5 up, 0 touch, -2 full pressure
A servo (selector)   lines the wanted colour's slider up with the clicker
B servo (clicker)    pushes that slider down until it latches, then lets go
```

A colour change happens with the pen up. `journal_plot` runs that colour's
`select` G-code, for example turn to 90, push, release, then carries on.
Each colour also has:

* its own **touch height**, because refills stick out by slightly different
  amounts,
* a small **tip offset**, because each refill's tip sits a fraction of a mm
  away from the others, which the plotter corrects by shifting the carriage,
* an **ink colour**, so strokes in the layout go to the nearest refill and the
  preview shows real colours.

## Hardware

### Selector

The selector servos ride on the pen mount, so the push force on a slider
stays inside the arm and can't shove the pen into the paper. A good layout for
pens with sliders spaced 90° apart (the BIC 4-Colour style):

* **A, selector**: turns the pen in a printed sleeve, so the clamp holds the
  sleeve and the pen turns inside it. Use **2:1 gearing**: a 180° servo
  can't reach a slider 270° away, but geared 2:1 it covers the full turn.
  Instead of turning the pen, A can turn a ring around the barrel that
  carries the clicker to the slider.
* **B, clicker**: a small arm that pushes the lined-up slider down about
  8-10 mm until it latches, then returns to rest so the arm clears all the
  sliders.
* Two 9-13 g micro servos (SG90, or MG90S for metal gears).
* Selectors that use one servo (for example a cam ring that pushes one slider
  at a time as it turns) only need A. Delete the `b:` axis from the config.

Printable selector parts aren't in this repo yet. The firmware and software
work with any selector you can drive with servo moves, so you can use your
own design or one adapted from elsewhere.

### Things to check

* **Fit**: multipens are fatter than the fineliner the midTbot pen clamp was
  drawn for. Check that the barrel fits the clamp before building the
  selector. A sleeve or a reprinted clamp may be needed.
* **Weight**: about 20-30 g of servos on the arm raises the pen's resting
  force. That's fine for ballpoint refills, which like firm pressure.
  Recalibrate the touch point and pressure range after fitting.
* **Cables**: run the two servo leads along the arm with a loose loop at the
  hinge so they don't tug on the pen.

### Wiring and power

| Servo | DevKitC-1 pin | GPIO | Config axis |
|---|---|---|---|
| Lift / pressure | J1 pin 9 | 16 | Z (unchanged) |
| Colour selector | J1 pin 12 | 8 | A |
| Clicker | J1 pin 20 | 14 | B |

Servo red to the 5 V rail, brown to GND, orange to the pin. With three servos,
use a 5 V regulator of at least 3 A (e.g. Pololu D36V28F5). Put the 470 µF
capacitor near where the servo leads join. The rest of the wiring is in
[esp32s3_upgrade.md](esp32s3_upgrade.md).

## Firmware

Use [`Firmware/FluidNC/midtbot_s3_multipen.yaml`](../Firmware/FluidNC/midtbot_s3_multipen.yaml)
instead of `midtbot_s3.yaml`. It's identical except for two servo axes:

* **A** spans 0-180 (about degrees). The servo follows the planned move, so
  `max_rate_mm_per_min` sets how fast it turns.
* **B** spans 0-10: 0 is rest, 10 is a full push. It's slower on purpose so
  the push is steady.

Both "home" with Z, so on `$H` the pen lifts, the clicker goes to rest and the
selector goes to 0 before X and Y move.

## Calibration

Copy [`Tools/journal_plot/profile.multipen.example.toml`](../Tools/journal_plot/profile.multipen.example.toml)
to `my_multipen.toml` and fill it in as you go.

1. **Clicker travel**: jog B (`$J=G91 B1 F600`). Adjust `min_pulse_us`/`max_pulse_us`
   on the `b:` axis until B = 0 clears every slider and B = 10 pushes a
   slider just far enough to latch.
2. **Selector positions**: jog A until each colour's slider sits under the
   clicker and note the A value. Each colour's `select` is then:
   ```toml
   select = ["G0 A90", "G0 B10", "G4 P0.2", "G0 B0"]   # line up, push, hold, release
   ```
3. **Touch heights**: the setup pause at the start of every job selects the
   first colour and sets the pen height with it, so that colour's
   `z_touch = 0`. For each other colour, send its select lines by hand, jog Z
   down until the tip just touches, and enter the Z you read as that colour's
   `z_touch`.
4. **Tip offsets**: run
   `python3 journal_plot.py --offset-test -p my_multipen.toml -o offset_test.gcode`
   and plot it. Every colour draws the same crosshair, and colour *n* also
   draws *n* ticks in its own row so you can tell them apart. Compare each
   cross with the first colour's. If it landed `d` mm further along machine
   +X, add `d` to that colour's `offset_x`. Do the same for Y. Re-run until the
   crosses overlap.
5. **Pressure per refill**: gel and ballpoint refills want different force.
   Set `z_max` per colour, and check line weight with `--test-pattern`.

## Laying out pages

No special setup is needed: draw in colour.

* Each stroke goes to the refill whose `color` is closest to its stroke
  colour, so any red becomes the red refill and any dark grey or black
  becomes black. Layers no longer have to match pens.
* To tie a layer to a colour explicitly, and give it its own pressure style:
  ```toml
  [pens."Headings"]
  slot = "black"
  down_boost = 0.4
  ```
* A pen that isn't part of the multipen, such as a brush pen you swap in by
  hand, keeps the manual pen-change pause:
  ```toml
  [pens."Brush pen"]
  slot = "manual"
  ```
* `--preview` draws every colour in its own ink, so the preview looks like the
  finished page.

[`Tools/journal_plot/examples/multipen_page.svg`](../Tools/journal_plot/examples/multipen_page.svg)
is a single-layer example: a black heading and note, a red reminder and heart,
blue waves and a green leaf.

```sh
cd Tools/journal_plot
python3 journal_plot.py examples/multipen_page.svg -p profile.multipen.example.toml --preview
```

The job starts with one pause: the first colour is selected, the pen sits at
its touch height, and you set the pen in the clamp and resume. After that it
switches colours on its own, drawing in layout order (black, red, blue,
green for the example) and selecting each colour once.
