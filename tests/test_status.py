from klipper_mcp.status import summarize_status, STATUS_OBJECTS

# Real payload from the Pi 2026-09-03, trimmed to the fields we read.
RAW = {
    "webhooks": {"state": "shutdown", "state_message": "Lost communication with MCU 'mcu'\n..."},
    "extruder": {"temperature": 21.99, "target": 0.0, "pressure_advance": 0.032},
    "heater_bed": {"temperature": 21.8, "target": 0.0},
    "print_stats": {"filename": "Body4_PLA_22m1s.gcode", "total_duration": 1475.09,
                    "print_duration": 1345.7, "filament_used": 8311.97, "state": "complete"},
    "toolhead": {"homed_axes": "", "position": [5.0, 290.0, 63.04, 61813.0]},
    "display_status": {"progress": 1.0},
    "fan": {"speed": 0.0},
    "gcode_move": {"speed_factor": 1.0, "extrude_factor": 1.0, "homing_origin": [0.0, 0.0, -0.01, 0.0]},
    "virtual_sdcard": {"progress": 1.0, "is_active": False},
}


def test_summary_shape_and_values():
    s = summarize_status(RAW)
    assert s["klippy"]["state"] == "shutdown"
    assert "MCU" in s["klippy"]["message"]
    assert s["job"]["state"] == "complete"
    assert s["job"]["filename"] == "Body4_PLA_22m1s.gcode"
    assert s["job"]["progress_percent"] == 100
    assert s["temps"]["extruder"] == {"actual": 22.0, "target": 0.0}
    assert s["temps"]["bed"]["actual"] == 21.8
    assert s["fan_percent"] == 0
    assert s["pressure_advance"] == 0.032
    assert s["z_offset"] == -0.01
    assert s["homed_axes"] == ""
    assert s["position"] == [5.0, 290.0, 63.04]


def test_missing_objects_do_not_crash():
    s = summarize_status({})
    assert s["klippy"]["state"] == "unknown"
    assert s["job"]["state"] is None
    assert s["temps"]["extruder"]["actual"] is None


def test_status_objects_include_webhooks():
    assert "webhooks" in STATUS_OBJECTS and "print_stats" in STATUS_OBJECTS
