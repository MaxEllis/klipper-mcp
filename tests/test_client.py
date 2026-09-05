import httpx, respx, pytest
from klipper_mcp.client import MoonrakerClient
from klipper_mcp.config import Config
from klipper_mcp.errors import NotReachable, BadRequest

B = "http://x:7125"
FB = "http://fb:7125"


def _cfg(fallback=None):
    return Config(base_url=B, fallback_url=fallback, timeout=5, printer_id="swx2")


# Real shape captured from the Pi 2026-09-03 (trimmed).
OBJECTS = {"result": {"eventtime": 1.0, "status": {
    "extruder": {"temperature": 21.99, "target": 0.0, "pressure_advance": 0.032},
    "heater_bed": {"temperature": 21.8, "target": 0.0},
    "print_stats": {"filename": "Body4_PLA_22m1s.gcode", "state": "complete",
                    "print_duration": 1345.7, "total_duration": 1475.09, "filament_used": 8311.97},
}}}


@respx.mock
async def test_objects_query_unwraps_status_and_sends_objects_as_params():
    route = respx.get(url__regex=rf"{B}/printer/objects/query.*").mock(
        return_value=httpx.Response(200, json=OBJECTS))
    async with MoonrakerClient(_cfg()) as c:
        st = await c.objects_query(["extruder", "print_stats"])
    assert st["extruder"]["temperature"] == 21.99
    assert st["print_stats"]["state"] == "complete"
    url = str(route.calls.last.request.url)
    assert "extruder" in url and "print_stats" in url


@respx.mock
async def test_history_list_returns_jobs():
    respx.get(url__regex=rf"{B}/server/history/list.*").mock(return_value=httpx.Response(
        200, json={"result": {"count": 1, "jobs": [{"job_id": "000092", "status": "completed"}]}}))
    async with MoonrakerClient(_cfg()) as c:
        jobs = await c.history_list(limit=5)
    assert jobs[0]["job_id"] == "000092"


@respx.mock
async def test_files_list_and_print_start_and_gcode_script():
    respx.get(url__regex=rf"{B}/server/files/list.*").mock(return_value=httpx.Response(
        200, json={"result": [{"path": "a.gcode", "modified": 1.0, "size": 10}]}))
    start = respx.post(url__regex=rf"{B}/printer/print/start.*").mock(
        return_value=httpx.Response(200, json={"result": "ok"}))
    script = respx.post(url__regex=rf"{B}/printer/gcode/script.*").mock(
        return_value=httpx.Response(200, json={"result": "ok"}))
    async with MoonrakerClient(_cfg()) as c:
        files = await c.files_list()
        assert files[0]["path"] == "a.gcode"
        assert await c.print_start("a.gcode") == "ok"
        assert await c.gcode_script("M117 hi") == "ok"
    assert "filename=a.gcode" in str(start.calls.last.request.url)
    assert "M117" in str(script.calls.last.request.url)


@respx.mock
async def test_upload_gcode_is_multipart_to_gcodes_root(tmp_path):
    p = tmp_path / "cube.gcode"
    p.write_text("G28\n")
    route = respx.post(f"{B}/server/files/upload").mock(return_value=httpx.Response(
        201, json={"result": {"item": {"path": "cube.gcode", "root": "gcodes"}, "print_started": False}}))
    async with MoonrakerClient(_cfg()) as c:
        out = await c.upload_gcode(str(p), "cube.gcode")
    assert out["item"]["path"] == "cube.gcode"
    body = route.calls.last.request.content
    assert b'name="file"' in body and b"cube.gcode" in body and b'name="root"' in body


@respx.mock
async def test_error_envelope_maps_to_badrequest():
    respx.post(url__regex=rf"{B}/printer/print/start.*").mock(return_value=httpx.Response(
        400, json={"error": {"code": 400, "message": "Unable to start print"}}))
    async with MoonrakerClient(_cfg()) as c:
        with pytest.raises(BadRequest, match="Unable to start print"):
            await c.print_start("a.gcode")


@respx.mock
async def test_falls_back_to_ip_when_primary_unreachable():
    respx.get(f"{B}/server/info").mock(side_effect=httpx.ConnectError("dns"))
    respx.get(f"{FB}/server/info").mock(return_value=httpx.Response(200, json={"result": {"klippy_state": "ready"}}))
    async with MoonrakerClient(_cfg(fallback=FB)) as c:
        info = await c.server_info()
        assert info["klippy_state"] == "ready"
        # subsequent calls stay on the fallback
        respx.get(f"{FB}/printer/info").mock(return_value=httpx.Response(200, json={"result": {"state": "ready"}}))
        assert (await c.printer_info())["state"] == "ready"


@respx.mock
async def test_unreachable_without_fallback_raises():
    respx.get(f"{B}/server/info").mock(side_effect=httpx.ConnectError("down"))
    async with MoonrakerClient(_cfg()) as c:
        with pytest.raises(NotReachable):
            await c.server_info()
