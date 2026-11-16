# Journal pages with pen pressure

This turns the midTbot into a journaling plotter: you lay a page out as a
vector file beforehand (handwriting-style text plus drawings), and the
plotter writes it into your notebook with real line-weight variation, such as
heavy downstrokes and light upstrokes from a brush pen, tapered stroke ends,
or a firm heading next to fine body text.

It has three parts:

| Part | What it does | File |
|---|---|---|
| Spring coupling | Lets the servo press the pen down, not just lift it | (this page) |
| FluidNC config | Maps servo Z below the paper so negative Z = more pressure | [`Firmware/FluidNC/midtbot_s3.yaml`](../Firmware/FluidNC/midtbot_s3.yaml) |
| `journal_plot` | Turns SVG pages into G-code with per-point pressure | [`Tools/journal_plot/`](../Tools/journal_plot/) |

The controller side (ESP32-S3, off-the-shelf parts) is in
[esp32s3_upgrade.md](esp32s3_upgrade.md). To switch colours automatically
with a multi-colour pen (BIC 4-Colour style), see [multipen.md](multipen.md).

## 1. How the pressure works

On the stock midTbot the pen mount hinges on the M3 x 50 screw through the
head block. The servo horn pushes the mount up to lift the pen, and gravity
puts it back down. The servo can't press, so every line gets the same
gravity-only force.

The fix is a spring between the servo horn and the pen mount:

```
 servo horn above contact  -> horn pushes the mount up      -> pen up      (Z = +5)
 horn at the contact angle -> spring just taut, no force   -> pen touches (Z =  0)
 horn rotated past contact -> spring stretches: F = k * dZ -> more pressure (Z < 0, down to -2)
```

Force grows with how far the horn turns past the contact angle, so servo
position becomes pen pressure. FluidNC treats the servo as the Z axis, and
the config spans Z = -2 to +5. Moving Z inside a drawing move (`G1 X.. Y.. Z..`)
changes pressure smoothly along the line.

## 2. Spring coupling (mechanical)

Parts, all generic:

* A small **extension spring**, about 4-6 mm OD, 15-25 mm long, 0.3-0.4 mm
  wire. Assortment boxes ("small extension spring kit") have several
  rates; start soft. A **rubber band** works for a first test but creeps
  over time, so line weight drifts.
* A short **M2 screw + nut** (or a small zip tie) as an anchor on the pen mount.

Fitting:

1. Power the servo at Z = 0 (the touch position, see calibration below) and
   find the point on the pen mount directly in line with the horn's outermost
   hole, on the side the horn moves away to when it lowers.
2. Fit the M2 anchor there. Drill 1.8 mm into the printed mount and let the
   screw self-tap, or zip-tie around the arm.
3. Hook the spring from the horn's outer hole to the anchor. At Z = 0 it
   should be straight but carry almost no tension.
4. Check:
   * At Z = +5 the horn still lifts the mount clear of the paper and the
     spring is slack.
   * At Z = -2 the spring is stretched, the pen presses visibly harder, and
     the servo does **not** buzz or stall. If it buzzes, use a softer spring or
     reduce `max_pulse_us`/`min_pulse_us` span so Z = -2 turns less far.
   * The hinge still swings freely, with no binding from the spring pulling
     sideways.

An MG90S (metal gear, ~2 kg-cm) is plenty: a brush pen at full pressure needs
roughly 100 g at the tip. A digital micro servo holds position more tightly
than an analog one and gives steadier light strokes, but it isn't required.

## 3. Calibration

Do this once per spring, and again if you change the spring.

1. **Home** the machine (`$H`). Z goes to +5, pen up.
2. **Pulse range**: jog Z to +5 and -2. At +5 the pen should clear the paper
   by 2-3 mm. At -2 the spring should be well stretched without servo strain.
   Adjust `min_pulse_us` / `max_pulse_us` in `config.yaml` until both are
   true. Swap the two values if the servo turns the wrong way.
3. **Touch point**: with a pen mounted, jog down in small steps,
   `$J=G91 Z-0.1 F600`, until the tip just touches the paper. Read Z from
   the status report (`?`).
   * Easiest: move to Z = 0 and loosen the pen clamp, let the pen rest on
     the paper, then tighten. Now the touch point is Z = 0 for every pen.
     `journal_plot` puts this step in the G-code automatically: before each
     pen it pauses at Z = 0 (`M0`) so you can mount and set the pen, then
     resume.
   * Or keep the pen where it is and set `z_touch` in your profile to the Z
     you read.
4. **Maximum pressure**: keep jogging down and watch the line weight on a
   scrap sheet. Stop where the line stops getting wider, or where a brush tip
   is fully splayed. Put that value in `z_max` (no lower than -2). Fineliners
   usually want a shallow `z_max` (about -0.5 to -1) to protect the tip.
5. **Optional, force curve**: put a kitchen or jewelry scale under the pen
   tip, tare it with the pen up, and write down grams at Z = 0, -0.5, -1,
   -1.5, -2. Enter them as `force_curve` in the profile. Pressure 0..1 then
   becomes linear in grams, which evens out a non-linear spring or servo.
6. **Test card**: run
   `python3 journal_plot.py --test-pattern -p my_pen.toml -o test.gcode`
   and plot it. You get five flat lines at pressure 0-1, the same five with
   long tapers, and a row of loops that should show thick downstrokes and
   thin upstrokes. Tune `min` (raise it if stroke starts skip), the tapers,
   and `down_boost` until it looks like your pen.

## 4. Laying out a page

Any SVG editor works. Inkscape (free) handles everything below.

* **Page size = plot area.** Set the document size to the area the plotter
  will draw. The stock frame reaches about 100 x 100 mm. A larger notebook
  page is laid out as several panels of 100 mm or less, moving the plotter
  between them. `origin_x` / `origin_y` in the profile place the page's
  lower-left corner on the machine.
* **Text must be single-line strokes.** Normal fonts are outlines and would
  plot as hollow letters. In Inkscape, type the text, then use
  *Extensions > Text > Hershey Text* with a script face (e.g. "Script
  1-stroke" or "EMS Allure"). `journal_plot` skips any leftover `<text>`
  element and tells you.
* **Layers are pens.** Each Inkscape layer is plotted as one pen, in layer
  order (e.g. "Brush pen" for headings, "Fineliner" for body text). Before
  each layer the plotter pauses for a pen change. To group objects by pen
  some other way, set `data-pen="name"` on them.
* **Line weight**, two ways:
  * Draw it: the stroke width in the layout sets pressure,
    `width_min` (0.2 mm) = lightest, `width_max` (2.0 mm) = heaviest. What
    you see in Inkscape is roughly what you get.
  * Or set it exactly: add `data-pressure="0.7"` (0 to 1) to an object, a
    group, or a whole layer via *Edit > XML Editor*. Children inherit it and
    can override it.
* **Guides**: ruled lines, margins, or a photo of the notebook page can go on
  a hidden layer. Hidden layers are never plotted.
* Strokes keep the direction you drew them. The tool reorders strokes to save
  travel but never reverses one, because direction decides which parts of a
  brush stroke are thick.

[`Tools/journal_plot/examples/sample_page.svg`](../Tools/journal_plot/examples/sample_page.svg)
is a complete example: a brush-pen date heading, three lines of single-stroke
cursive in fineliner, a small leaf sketch, and a hidden guides layer.

## 5. Plotting

```sh
cd Tools/journal_plot
pip install -r requirements.txt            # svgelements (+ pytest for the tests)
cp profile.example.toml my_pen.toml        # put your calibration in here
python3 journal_plot.py page.svg -p my_pen.toml --preview
```

This writes `page.gcode` and `page_preview.svg`. Open the preview in a
browser: line width shows the planned pressure, so you can check the page
before it touches the notebook. The command also prints stroke count, ink
length and an estimated time, and it refuses to write G-code that leaves the
machine area (`--force` overrides).

Upload `page.gcode` to the SD card from the FluidNC WebUI and run it. At each
pen pause (the servo is at the touch angle), mount the pen so the tip just
rests on the paper, tighten the clamp, and press *Resume* (or send `~`).

Per-pen settings in the profile, keyed by layer name:

```toml
[pens."Brush pen"]
down_boost = 0.6     # upstrokes 60 % lighter than downstrokes
taper_out = 2.5
draw_feed = 900      # slower lets a brush lay down ink

[pens."Fineliner"]
z_max = -1.0         # never press a fine tip hard
```

## 6. Previewing with real pens (Pilot G2)

By default the preview uses line width to stand for pressure. If you tell
`journal_plot` which pen a layer is drawn with, it simulates that pen
instead: every stroke is drawn at the width of line the pen really lays down,
nudged a little by pressure, so the preview shows what will be on the paper.

```toml
[pens."G2 0.7"]
tip = "g2-0.7"        # or: line_width = 0.39  (mm, for any other pen)
```

| Tip | Line on paper | Source |
|---|---|---|
| `g2-0.38` | about 0.26 mm | estimated from the ratio of the two below |
| `g2-0.5` | about 0.32 mm | retailer listing |
| `g2-0.7` | 0.39 mm | Pilot |
| `g2-1.0` | about 0.52 mm | estimated |

A gel pen's line barely changes with pressure, so `line_flex` (default 0.13,
meaning ±13 %) keeps the simulation honest: with these pens, tone comes from
how many lines you lay down and which tip you use, not from pressing harder.
If your pens measure differently, set `line_width` yourself.

[`profile.g2.example.toml`](../Tools/journal_plot/profile.g2.example.toml)
sets up all four tips, one per layer. The example drawing
[`examples/raccoon_sketch.svg`](../Tools/journal_plot/examples/raccoon_sketch.svg)
uses them the way an illustrator would: the 1.0 for solid blacks, 0.7 and
0.5 for the darks, and the 0.38 for fine fur. Lights, whiskers and the glints
in the eyes are paper left untouched. It fills a 94 × 94 mm page: about
6,000 strokes, 15 m of ink, an hour of plotting and four pen changes.

```sh
python3 journal_plot.py examples/raccoon_sketch.svg -p profile.g2.example.toml --preview
```

## 7. Tips

* Keep the notebook flat and still: clip it, or put a steel sheet underneath
  and use magnets. The plotter's feet sit on the page, so the pages under
  them must not shift.
* The pen pause happens at `park_x`/`park_y`. Choose a spot in the margin,
  because the tip touches the paper there while you set it.
* If light strokes come out patchy, raise `min` slightly, or slow `draw_feed`
  for that pen.
* The servo updates every 20 ms. At 1500 mm/min that's a pressure change
  every 0.5 mm, which is smooth for handwriting-sized strokes.
