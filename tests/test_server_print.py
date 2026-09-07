import httpx, respx
import klipper_mcp.server as srv
from klipper_mcp import outcomes as oc

B = "http://x:7125"
READY = {"result": {"state": "ready", "state_message": "Printer is ready"}}
IDLE = {"result": {"status": {"webhooks": {"state": "ready"}, "print_stats": {"state": "standby", "filename": ""},
                              "display_status": {"progress": 0.0}}}}


def _env(m):
    m.setenv("MOONRAKER_URL", B); m.setenv("MOONRAKER_FALLBACK_URL", "")
    respx.get(f"{B}/printer/info").mock(return_value=httpx.Response(200, json=READY))
    respx.get(url__regex=rf"{B}/printer/objects/query.*").mock(return_value=httpx.Response(200, json=IDLE))
    respx.get(url__regex=rf"{B}/server/files/list.*").mock(return_value=httpx.Response(
        200, json={"result": [{"path": "onpi.gcode", "modified": 1.0, "size": 5}]}))


@respx.mock
async def test_start_print_local_file_previews_then_uploads_and_starts(monkeypatch, tmp_path):
    _env(monkeypatch)
    p = tmp_path / "cube_PLA_20m.gcode"; p.write_text("G28\n")
    up = respx.post(f"{B}/server/files/upload").mock(return_value=httpx.Response(
        201, json={"result": {"item": {"path": "cube_PLA_20m.gcode", "root": "gcodes"}}}))
    start = respx.post(url__regex=rf"{B}/printer/print/start.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    prev = await srv.start_print(str(p))
    assert prev["confirm_required"] and prev["preview"]["filename"] == "cube_PLA_20m.gcode"
    assert prev["preview"]["upload_needed"] is True and prev["preview"]["size_bytes"] == 4
    assert prev["preview"]["overwrites_existing"] is False
    assert not up.called and not start.called
    out = await srv.start_print(str(p), confirm=True)
    assert out["ok"] and out["uploaded"] is True and up.called
    assert out["overwrites_existing"] is False
    assert "filename=cube_PLA_20m.gcode" in str(start.calls.last.request.url)


@respx.mock
async def test_start_print_local_file_discloses_overwrite(monkeypatch, tmp_path):
    _env(monkeypatch)
    p = tmp_path / "onpi.gcode"; p.write_text("G28\n")
    prev = await srv.start_print(str(p))
    assert prev["preview"]["overwrites_existing"] is True


@respx.mock
async def test_start_print_local_non_gcode_suffix_is_refused(monkeypatch, tmp_path):
    _env(monkeypatch)
    up = respx.post(f"{B}/server/files/upload").mock(return_value=httpx.Response(201, json={"result": {}}))
    p = tmp_path / "notes.txt"; p.write_text("hello\n")
    out = await srv.start_print(str(p))
    assert out["error"] == "not_gcode" and not up.called


@respx.mock
async def test_start_print_pi_subdirectory_file(monkeypatch):
    _env(monkeypatch)
    respx.get(url__regex=rf"{B}/server/files/list.*").mock(return_value=httpx.Response(
        200, json={"result": [{"path": "sub/deep.gcode", "modified": 1.0, "size": 5}]}))
    up = respx.post(f"{B}/server/files/upload").mock(return_value=httpx.Response(201, json={"result": {}}))
    start = respx.post(url__regex=rf"{B}/printer/print/start.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    out = await srv.start_print("sub/deep.gcode", confirm=True)
    assert out["ok"] and out["filename"] == "sub/deep.gcode" and not up.called
    assert start.calls.last.request.url.params["filename"] == "sub/deep.gcode"


@respx.mock
async def test_start_print_reports_upload_succeeded_when_start_fails(monkeypatch, tmp_path):
    _env(monkeypatch)
    p = tmp_path / "cube_PLA_20m.gcode"; p.write_text("G28\n")
    respx.post(f"{B}/server/files/upload").mock(return_value=httpx.Response(
        201, json={"result": {"item": {"path": "cube_PLA_20m.gcode", "root": "gcodes"}}}))
    respx.post(url__regex=rf"{B}/printer/print/start.*").mock(return_value=httpx.Response(
        400, json={"error": {"message": "bad file"}}))
    out = await srv.start_print(str(p), confirm=True)
    assert out["uploaded"] is True and "error" in out and out["filename"] == "cube_PLA_20m.gcode"


@respx.mock
async def test_start_print_existing_pi_file_skips_upload(monkeypatch):
    _env(monkeypatch)
    up = respx.post(f"{B}/server/files/upload").mock(return_value=httpx.Response(201, json={"result": {}}))
    start = respx.post(url__regex=rf"{B}/printer/print/start.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    prev = await srv.start_print("onpi.gcode")
    assert prev["preview"]["upload_needed"] is False
    out = await srv.start_print("onpi.gcode", confirm=True)
    assert out["ok"] and out["uploaded"] is False and not up.called and start.called


@respx.mock
async def test_start_print_missing_file_is_an_error(monkeypatch):
    _env(monkeypatch)
    out = await srv.start_print("/nope/missing.gcode")
    assert out["error"] == "file_not_found"


@respx.mock
async def test_start_print_refuses_while_printing(monkeypatch):
    _env(monkeypatch)
    respx.get(url__regex=rf"{B}/printer/objects/query.*").mock(return_value=httpx.Response(200, json={
        "result": {"status": {"webhooks": {"state": "ready"}, "print_stats": {"state": "printing", "filename": "busy.gcode"},
                              "display_status": {"progress": 0.5}}}}))
    out = await srv.start_print("onpi.gcode", confirm=True)
    assert out["error"] == "printer_busy" and out["current"]["filename"] == "busy.gcode"


def test_record_verdict(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    oc.record_outcome({"job_id": "1", "filename": "a.gcode", "status": "completed", "end_time": 5.0})
    out = srv.record_verdict("warped at the corners")
    assert out["human_verdict"] == "warped at the corners" and out["gcode_filename"] == "a.gcode"
    assert srv.record_verdict("x", gcode_filename="nope.gcode")["error"] == "no_printed_job_found"


PAUSED = {"result": {"status": {"webhooks": {"state": "ready"},
                                "print_stats": {"state": "paused", "filename": "running.gcode"},
                                "display_status": {"progress": 0.42}}}}


@respx.mock
async def test_start_print_refuses_while_paused(monkeypatch, tmp_path):
    # A paused job still owns the printer: starting another would clobber it.
    _env(monkeypatch)
    respx.get(url__regex=rf"{B}/printer/objects/query.*").mock(return_value=httpx.Response(200, json=PAUSED))
    start = respx.post(url__regex=rf"{B}/printer/print/start.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    p = tmp_path / "next.gcode"; p.write_text("G28\n")
    for confirm in (False, True):
        out = await srv.start_print(str(p), confirm=confirm)
        assert out["error"] == "printer_busy"
        assert out["current"] == {"filename": "running.gcode", "job_state": "paused", "progress_percent": 42}
    assert not start.called
