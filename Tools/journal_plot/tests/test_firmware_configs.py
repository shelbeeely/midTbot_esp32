"""Consistency checks for the FluidNC configs in Firmware/FluidNC."""
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

FW = Path(__file__).resolve().parents[3] / "Firmware" / "FluidNC"
SINGLE = FW / "midtbot_s3.yaml"
MULTI = FW / "midtbot_s3_multipen.yaml"


def pins(path):
    code = "".join(line.split("#")[0] + "\n" for line in path.read_text().splitlines())
    return re.findall(r"gpio\.(\d+)", code)


@pytest.mark.parametrize("path", [SINGLE, MULTI])
def test_no_pin_used_twice(path):
    p = pins(path)
    assert len(p) == len(set(p))


@pytest.mark.parametrize("path", [SINGLE, MULTI])
def test_avoids_s3_reserved_pins(path):
    # strapping 0/3/45/46, USB 19/20, UART0 43/44, flash/PSRAM 26-37, RGB LED 38/48
    reserved = {0, 3, 45, 46, 19, 20, 43, 44, 38, 48, *range(26, 38)}
    assert not reserved & {int(p) for p in pins(path)}


def test_pen_z_range_matches_journal_plot_defaults():
    z = yaml.safe_load(SINGLE.read_text())["axes"]["z"]
    top = z["homing"]["mpos_mm"]
    assert (top - z["max_travel_mm"], top) == (-2, 5)


def test_multipen_config_only_adds_selector_axes():
    single = yaml.safe_load(SINGLE.read_text())
    multi = yaml.safe_load(MULTI.read_text())
    for key in ("kinematics", "stepping", "spi", "sdcard", "start"):
        assert multi[key] == single[key]
    for axis in ("x", "y", "z"):
        assert multi["axes"][axis] == single["axes"][axis]
    assert "rc_servo" in multi["axes"]["a"]["motor0"]
    assert "rc_servo" in multi["axes"]["b"]["motor0"]
