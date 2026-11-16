# MidTBot ESP32

![](https://github.com/bdring/midTbot_esp32/blob/master/Docs/images/20190721_092227.jpg)

The MidTBot is a small and simple little pen plotter. All of the custom parts are 3D printed. The rest of the parts are low cost and easy to get.

The controller uses an ESP32 running Grbl_ESP32 firmware. It can be controlled via USB, Bluetooth or Wifi. You can simply upload gcode files to the unboard SD card and print.


The machine is controlled by a unique H-bot configuration, that uses a single belt. Two small stepper motors drive that belt in a special way to move in the X/Y plane. The pen is lifted by a hobby servo using a very simple and accurate mechanism.

[Here is a link to a video of the plotter in action.](https://www.youtube.com/watch?v=jiwWCrCfXrY)

The project is open source (Creative commons 4.0 Attribution - Share Alike) and all the files are in this Githob repo. Assembly instructions [are here](https://github.com/bdring/midTbot_esp32/wiki/Assembly-Instructions). If you have questions, please ask them by opening an issue in this repo.

### Check it out on GrabCad

Click on image for interactive viewer in browser.

[![GrabCAD](https://github.com/bdring/midTbot_esp32/blob/master/Docs/images/grabcad_model.png)](https://workbench.grabcad.com/workbench/projects/gcj3zJAQexD3ve_8KkwymatyKXhCWnRs8TB5U1ojGxl3s4#/space/gcP-lh4vchvUQ6FbfQFYGKVWLmIdnV8aq2IyxzoECw8woR/link/1918044)

### Kits

There currently are no full kits for sale, and the original controller kit is no longer available. The controller can be built from off-the-shelf parts instead; see below.

### 2026 upgrade: ESP32-S3 and pen pressure

* [ESP32-S3 controller from off-the-shelf parts](Docs/esp32s3_upgrade.md): ESP32-S3-DevKitC-1, TMC2209 StepSticks and FluidNC 4.x, plus a printed [controller plate](STL/midt_esp32s3_controller_plate.stl) that takes the old PCB's place under the motors and limit switches.
* [Journal pages with pen pressure](Docs/journal_pages.md): a spring between servo and pen mount, so the servo can press as well as lift. Lay pages out as SVG and [`journal_plot`](Tools/journal_plot) plots them with varying line weight (tapered strokes, brush-style thick downstrokes, one pen per layer).
* [Multipen](Docs/multipen.md): use a multi-colour pen (BIC 4-Colour, Jetstream 4&1, Sarasa Multi...) with a servo selector, and the plotter switches colours mid-page by itself. Strokes go to the refill nearest their colour in the layout.
* Real-pen previews: tell `journal_plot` which pen a layer uses (Pilot G2 0.38, 0.5, 0.7 or 1.0, or any line width) and the preview draws it at its true width. The [raccoon example](Tools/journal_plot/examples/raccoon_sketch.svg) is drawn for all four G2 tips.
* FluidNC configs: [`midtbot_s3.yaml`](Firmware/FluidNC/midtbot_s3.yaml) (single pen), [`midtbot_s3_multipen.yaml`](Firmware/FluidNC/midtbot_s3_multipen.yaml) (adds the colour-selector servos).

### Donation

This project represents a lot of work. Please consider a safe, secure and highly appreciated donation via the PayPal link below.

[![](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=TKNJ9Z775VXB2)
