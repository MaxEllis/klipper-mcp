import json
from klipper_mcp import outcomes as oc

JOB = {"job_id": "000092", "filename": "cube_PLA_20m.gcode", "status": "completed",
       "start_time": 1788152543.3, "end_time": 1788154018.4, "print_duration": 1345.7,
       "total_duration": 1475.09, "filament_used": 8311.97,
       "metadata": {"filament_weight_total": 24.67, "layer_height": 0.6, "first_layer_extr_temp": 230.0,
                    "first_layer_bed_temp": 60.0, "filament_type": "PLA", "filament_name": "PLA Fast @SWX2 0.8mm",
                    "nozzle_diameter": 0.8}}
SETTINGS = {"layer_height": "0.5", "nozzle_temperature": "230", "fan_max_speed": "60", "unrelated": "x"}


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))


def test_not_available_until_created(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert oc.is_available() is False
    oc.connect(create=True).close()
    assert oc.is_available() is True
    assert oc.db_path().name == "outcomes.db"


def test_slice_then_outcome_joins_on_filename(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    oc.connect(create=True).close()
    sid = oc.record_slice("cube_PLA_20m.gcode", "cube20", "abc123", SETTINGS, sliced_at=1788152000.0)
    oid = oc.record_outcome(JOB)
    assert oid == sid  # same row, not a second one
    rows = oc.recall(model_name="cube20")
    assert len(rows) == 1
    r = rows[0]
    assert r["result"] == "success" and r["filament_g"] == 24.67 and r["human_verdict"] is None
    assert r["settings_summary"]["layer_height"] == "0.5"
    assert "unrelated" not in r["settings_summary"]
    assert r["duration_s"] == 1475.09


def test_outcome_without_slice_row_inserts_with_metadata_subset(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    oid = oc.record_outcome(JOB)  # store auto-created
    rows = oc.recall(limit=5)
    assert rows[0]["id"] == oid and rows[0]["model_name"] == "cube_PLA_20m"
    assert rows[0]["settings_summary"]["layer_height"] == 0.6
    assert rows[0]["settings_summary"]["filament_type"] == "PLA"


def test_record_outcome_is_idempotent_on_job_id(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    a = oc.record_outcome(JOB)
    b = oc.record_outcome(JOB)
    assert a == b and len(oc.recall(limit=10)) == 1


def test_join_picks_newest_unprinted_slice_for_repeated_filename(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    oc.connect(create=True).close()
    old = oc.record_slice("cube_PLA_20m.gcode", "cube20", "h1", {"layer_height": "0.3"}, sliced_at=100.0)
    new = oc.record_slice("cube_PLA_20m.gcode", "cube20", "h1", {"layer_height": "0.5"}, sliced_at=200.0)
    assert oc.record_outcome(JOB) == new
    # a second finished job for the same file claims the remaining slice row
    assert oc.record_outcome({**JOB, "job_id": "000093"}) == old


def test_result_mapping_and_verdict_and_last_end(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert oc.result_for_status("completed") == "success"
    assert oc.result_for_status("cancelled") == "cancelled"
    assert oc.result_for_status("klippy_shutdown") == "error"
    oc.record_outcome({**JOB, "status": "cancelled"})
    out = oc.set_verdict("warped")
    assert out["human_verdict"] == "warped" and out["gcode_filename"] == "cube_PLA_20m.gcode"
    assert oc.recall(limit=1)[0]["human_verdict"] == "warped"
    assert oc.last_job_end_time() == 1788154018.4


def test_last_end_zero_when_empty_or_absent(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert oc.last_job_end_time() == 0.0


def test_geometry_hash_is_stable_and_order_independent():
    a = [{"name": "cube", "size_mm": [20, 20, 20.01]}, {"name": "peg", "size_mm": [5, 5, 30]}]
    b = list(reversed(a))
    assert oc.geometry_hash_for(a) == oc.geometry_hash_for(b)
    assert oc.geometry_hash_for(a) != oc.geometry_hash_for([{"name": "cube", "size_mm": [21, 20, 20]}])
