# journal_plot

Turns vector journal pages (SVG) into midTbot G-code with variable pen
pressure: line weight from stroke width or `data-pressure`, tapered stroke
ends, brush-style thick downstrokes, one pen per Inkscape layer, and
automatic colour switching on a multi-colour pen.

```sh
pip install -r requirements.txt
python3 journal_plot.py examples/sample_page.svg -p profile.example.toml --preview
python3 journal_plot.py --test-pattern -p profile.example.toml -o test.gcode

# multipen (one pen body, several colour refills)
python3 journal_plot.py examples/multipen_page.svg -p profile.multipen.example.toml --preview
python3 journal_plot.py --offset-test -p profile.multipen.example.toml -o offset_test.gcode

python3 -m pytest tests
```

Guides: [Docs/journal_pages.md](../../Docs/journal_pages.md) (pressure, calibration,
page layout) and [Docs/multipen.md](../../Docs/multipen.md) (colour selector).
Firmware configs: [Firmware/FluidNC/](../../Firmware/FluidNC/).
