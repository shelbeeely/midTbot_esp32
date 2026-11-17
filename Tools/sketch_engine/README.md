# sketch_engine

Draws a photo the way an artist works a pen sketch: loose gesture, construction with corrections,
contours traced from the photo, then layered hatching that builds the values up, and accents.
Every mark is a timed, pressure-sampled stroke, so the same drawing gives:

- `drawing.png`: the finished sketch, rendered with true G2 gel (or ballpoint) ink
- `compare.jpg`: the photo beside the drawing
- `report.json`: how close the values are to the photo after each stage
- `drawing.svg`: one layer per ink, ready for `journal_plot` and the plotter
- `replay.mp4` (with `--video`): a drawing-app replay, stroke by stroke

```sh
pip install numpy pillow opencv-python-headless
python3 sketch.py grid examples/raccoon.toml            # gridded photo, for measuring regions
python3 sketch.py run  examples/raccoon.toml --video
python3 -m pytest tests
```

A subject file (see `examples/raccoon.toml`) names the photo and the page, a handful of regions
(outline, inks light → dark, priority) and boxes around the features worth tracing. Everything
else comes from the photo and from the lessons in [LESSONS.md](LESSONS.md).

The example photo is a raccoon by Jim Osdale, Flickr, Public Domain Mark 1.0.
