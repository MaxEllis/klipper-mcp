import pytest
from klipper_mcp import gate
from klipper_mcp.errors import Refused, PrinterNotReady


def test_confirm_required_shape():
    out = gate.confirm_required("set_temperature", {"heater": "extruder", "target": 210})
    assert out["confirm_required"] is True and out["action"] == "set_temperature"
    assert out["preview"]["target"] == 210
    assert "confirm=true" in out["how"].lower()


def test_bounds_refuse_and_allow():
    gate.check_bounds(extruder_c=300, bed_c=110, pressure_advance=0.05, z_offset=-0.1, flow_percent=95, fan_percent=100)
    for bad in ({"extruder_c": 301}, {"bed_c": 111}, {"pressure_advance": 1.5}, {"z_offset": 2.5},
                {"flow_percent": 40}, {"fan_percent": 101}, {"extruder_c": -1}):
        with pytest.raises(Refused):
            gate.check_bounds(**bad)


def test_tune_gcode_lines():
    lines = gate.tune_gcode(pressure_advance=0.04, z_offset=-0.05, flow_percent=97, fan_percent=50)
    assert lines == ["SET_PRESSURE_ADVANCE ADVANCE=0.04", "SET_GCODE_OFFSET Z=-0.05 MOVE=1",
                     "M221 S97", "M106 S128"]
    assert gate.tune_gcode() == []


def test_require_ready():
    gate.require_ready({"state": "ready"})
    with pytest.raises(PrinterNotReady, match="shutdown"):
        gate.require_ready({"state": "shutdown", "state_message": "Lost communication with MCU"})
