import httpx, respx
import klipper_mcp.server as srv

B = "http://x:7125"


def _env(m):
    m.setenv("MOONRAKER_URL", B); m.setenv("MOONRAKER_FALLBACK_URL", "")


@respx.mock
async def test_get_printer_status_summarizes(monkeypatch):
    _env(monkeypatch)
    respx.get(url__regex=rf"{B}/printer/objects/query.*").mock(return_value=httpx.Response(200, json={
        "result": {"status": {"webhooks": {"state": "ready", "state_message": "Printer is ready"},
                              "extruder": {"temperature": 210.2, "target": 210.0},
                              "heater_bed": {"temperature": 60.0, "target": 60.0},
                              "print_stats": {"state": "printing", "filename": "a.gcode",
                                              "print_duration": 100.0, "total_duration": 120.0, "filament_used": 5.0},
                              "display_status": {"progress": 0.25}}}}))
    out = await srv.get_printer_status()
    assert out["klippy"]["state"] == "ready"
    assert out["job"]["state"] == "printing" and out["job"]["progress_percent"] == 25
    assert out["temps"]["extruder"]["target"] == 210.0


@respx.mock
async def test_get_printer_status_unreachable_is_an_error_dict(monkeypatch):
    _env(monkeypatch)
    respx.get(url__regex=rf"{B}/printer/objects/query.*").mock(side_effect=httpx.ConnectError("down"))
    out = await srv.get_printer_status()
    assert "error" in out and "not reachable" in out["error"]


@respx.mock
async def test_get_printer_info(monkeypatch):
    _env(monkeypatch)
    respx.get(f"{B}/printer/info").mock(return_value=httpx.Response(200, json={"result": {
        "state": "shutdown", "state_message": "Lost communication with MCU 'mcu'\nUse FIRMWARE_RESTART",
        "software_version": "v0.13.0-595-gb0e6ca45f", "hostname": "Klipper"}}))
    out = await srv.get_printer_info()
    assert out["state"] == "shutdown" and "FIRMWARE_RESTART" in out["message"]
    assert out["software_version"].startswith("v0.13")


@respx.mock
async def test_list_print_history_summarizes_jobs(monkeypatch):
    _env(monkeypatch)
    respx.get(url__regex=rf"{B}/server/history/list.*").mock(return_value=httpx.Response(200, json={
        "result": {"count": 1, "jobs": [{"job_id": "000092", "filename": "Body4_PLA_22m1s.gcode",
                                          "status": "completed", "start_time": 1788152543.3, "end_time": 1788154018.4,
                                          "print_duration": 1345.7, "total_duration": 1475.09, "filament_used": 8311.97,
                                          "metadata": {"filament_weight_total": 24.67, "layer_height": 0.6,
                                                       "filament_name": "PLA Fast @SWX2 0.8mm"}}]}}))
    out = await srv.list_print_history(limit=5)
    j = out["jobs"][0]
    assert j["job_id"] == "000092" and j["result"] == "success"
    assert j["duration_min"] == 25 and j["filament_g"] == 24.7
    assert j["layer_height"] == 0.6


@respx.mock
async def test_list_gcode_files_sorted_newest_first(monkeypatch):
    _env(monkeypatch)
    respx.get(url__regex=rf"{B}/server/files/list.*").mock(return_value=httpx.Response(200, json={
        "result": [{"path": "old.gcode", "modified": 1.0, "size": 10},
                   {"path": "new.gcode", "modified": 2.0, "size": 20}]}))
    out = await srv.list_gcode_files(limit=1)
    assert out["count"] == 1 and out["total"] == 2 and [f["path"] for f in out["files"]] == ["new.gcode"]


@respx.mock
async def test_list_print_history_clamps_limit_to_moonraker_range(monkeypatch):
    _env(monkeypatch)
    route = respx.get(url__regex=rf"{B}/server/history/list.*").mock(
        return_value=httpx.Response(200, json={"result": {"count": 0, "jobs": []}}))
    await srv.list_print_history(limit=500)
    assert route.calls.last.request.url.params["limit"] == "100"
    await srv.list_print_history(limit=0)
    assert route.calls.last.request.url.params["limit"] == "1"
    await srv.list_print_history(limit=-7)
    assert route.calls.last.request.url.params["limit"] == "1"
