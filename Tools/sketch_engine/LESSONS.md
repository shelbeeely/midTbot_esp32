# Lessons from the sketches so far

Every sketch in this project (raccoon, skylines, llama, the GRWM page, the windowsill, three
attempts at a portrait) taught something. Each lesson below says what went wrong, what fixed it,
and where the engine now does it by default, so it doesn't have to be learned again.

## Values

| Lesson | What happened | Built in |
|---|---|---|
| Measure white and black inside each region, never over the whole photo | Face hatched orange all over; then a navy sweater with the tie-dye lost; then a wall covered in orange rain. Each time the scale came from the wrong part of the photo. | `analyse.Study._calibrate`: per-region percentiles, anchored to the photo's own white/black so a light region isn't shaded all over |
| Paint out features before reading skin values | Dark glasses frames were read as skin shadow and buried the eyes in hatching. | `paint_out` in a region: polygons, ellipses and rings are inpainted before measuring |
| Check values against the photo after every stage | Most bad results looked fine stroke by stroke and wrong as a whole. | `Study.likeness`, printed per stage and saved in `report.json` |
| Build up what is still too light | One layered pass leaves the face sparse next to hand-finished drawings. | fill passes in `sketch.run` add the darkest ink only where the value is still short |
| Leave the background unfinished | Rendering the room to full value competed with the face. | `priority` per region; finish falls off 1.0 / 0.85 / 0.6 / 0.3 |

## Marks

| Lesson | What happened | Built in |
|---|---|---|
| Hatch in patches of parallel strokes | Scattered dashes read as rain or confetti. | `marks.zigzag_hatch` |
| Join dense rows into zig-zags; keep sparse rows separate | Zig-zags across sparse rows drew visible boxes. | `zigzag_hatch` lifts the pen when rows are far apart |
| Follow the photo's own forms | Strokes at one fixed angle made everything flat. | `Study.angle`: smoothed structure tensor, blended to a per-region fallback angle where the photo has no direction |
| Hair is long strands, not hatching | Hatched hair looked like a wig made of tiles. | `marks.strands` for `kind = "hair"` |
| Narrow bands are drawn along their length | Hatching couldn't fit into the 0.75 mm rims of the glasses, so they vanished. | `arcs` regions + `marks.arc_bands` |
| Feature lines come from the photo, not from guesses | Hand-measured splines drifted, and likeness drifted with them. | `Study.trace` (Canny edges near named features); pressure follows edge contrast |
| No flyaways sticking out like spines; no scribbles over flat background | Both read as damage, not energy. | scribbles only where a subject file asks for them |

## Ink

| Lesson | What happened | Built in |
|---|---|---|
| Gel ink is opaque: tone only from spacing | Translucent previews promised blends the pen can't make. | `replay.Canvas` `gel` model; `ballpoint` model is separate |
| Line width from the real tip at page scale | Lines were drawn several times too thick. | `palette.TIPS` × page scale |
| A new line never lightens what is under it | Burgundy laid over black turned the raccoon's mask red. | gel overlap darkens toward the darker colour |
| Each ink owns a band of the value range; darks end in the darkest ink | Light inks took most of the tone before black got a turn. | value bands per ink in `sketch.run` |
| Few inks per area | Six inks in one patch looked like confetti. | `inks` list per region, 1–4 inks |
| Ink colours from Pilot's PMS guide | Guessed colours drifted. | `palette.G2` (estimates marked) |

## Process and replay

| Lesson | What happened | Built in |
|---|---|---|
| Stable random seeds | `hash()` changes every run, so revising one pass reshuffled all the others. | `timeline.stable_rng` (crc32) |
| Video follows drawing order | Sections popping in at random don't read as drawing. | phases: gesture → construction → contours → tone → accents; tone ordered outward from `focus` |
| No per-stroke minimum when compressing a phase | A 0.02 s floor turned a 2-minute target into 3+ minutes. | `Timeline.pace`: floor only for gesture and construction |
| Show corrections | Real drawings are searched for. | an erased outline and an undone feature line in construction |

## Still open
- Eyes are hatched blobs; they need a dedicated iris, pupil and catchlight mark.
- Lips and other small warm areas over- or under-shoot with only one ink.
- Hands lose their form: knuckles need form-following guides, not just the photo's orientation.
