from klipper_mcp.status import summarize_status, STATUS_OBJECTS

# Shape of a real Moonraker reply, trimmed to the fields we read; the values are invented.
RAW = {
    "webhooks": {"state": "shutdown", "state_message": "Lost communication with MCU 'mcu'\n..."},
    "extruder": {"temperature": 23.96, "target": 0.0, "pressure_advance": 0.045},
    "heater_bed": {"temperature": 22.6, "target": 0.0},
    "print_stats": {"filename": "bracket_PLA_25m.gcode", "total_duration": 1500.0,
                    "print_duration": 1400.0, "filament_used": 4100.0, "state": "complete"},
    "toolhead": {"homed_axes": "", "position": [10.0, 200.0, 42.5, 1234.5]},
    "display_status": {"progress": 1.0},
    "fan": {"speed": 0.0},
    "gcode_move": {"speed_factor": 1.0, "extrude_factor": 1.0, "homing_origin": [0.0, 0.0, -0.05, 0.0]},
    "virtual_sdcard": {"progress": 1.0, "is_active": False},
}


def test_summary_shape_and_values():
    s = summarize_status(RAW)
    assert s["klippy"]["state"] == "shutdown"
    assert "MCU" in s["klippy"]["message"]
    assert s["job"]["state"] == "complete"
    assert s["job"]["filename"] == "bracket_PLA_25m.gcode"
    assert s["job"]["progress_percent"] == 100
    assert s["temps"]["extruder"] == {"actual": 24.0, "target": 0.0}
    assert s["temps"]["bed"]["actual"] == 22.6
    assert s["fan_percent"] == 0
    assert s["pressure_advance"] == 0.045
    assert s["z_offset"] == -0.05
    assert s["homed_axes"] == ""
    assert s["position"] == [10.0, 200.0, 42.5]


def test_missing_objects_do_not_crash():
    s = summarize_status({})
    assert s["klippy"]["state"] == "unknown"
    assert s["job"]["state"] is None
    assert s["temps"]["extruder"]["actual"] is None


def test_status_objects_include_webhooks():
    assert "webhooks" in STATUS_OBJECTS and "print_stats" in STATUS_OBJECTS
