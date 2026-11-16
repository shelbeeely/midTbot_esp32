# journal_plot

Turns vector journal pages (SVG) into midTbot G-code with variable pen
pressure: line weight from stroke width or `data-pressure`, tapered stroke
ends, brush-style thick downstrokes, and one pen per Inkscape layer.

```sh
pip install -r requirements.txt
python3 journal_plot.py examples/sample_page.svg -p profile.example.toml --preview
python3 journal_plot.py --test-pattern -p profile.example.toml -o test.gcode
python3 -m pytest tests
```

Setup, calibration and page-layout guide: [Docs/journal_pages.md](../../Docs/journal_pages.md).
Firmware config it targets: [Firmware/FluidNC/midtbot_s3.yaml](../../Firmware/FluidNC/midtbot_s3.yaml).
