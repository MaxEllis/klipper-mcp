import httpx, respx
import klipper_mcp.server as srv

B = "http://x:7125"
READY = {"result": {"state": "ready", "state_message": "Printer is ready"}}
SHUT = {"result": {"state": "shutdown", "state_message": "Lost communication with MCU 'mcu'"}}
STATUS = {"result": {"status": {"webhooks": {"state": "ready"}, "extruder": {"temperature": 25.0, "target": 0.0},
                                "heater_bed": {"temperature": 24.0, "target": 0.0},
                                "print_stats": {"state": "printing", "filename": "a.gcode"},
                                "display_status": {"progress": 0.4}}}}


def _env(m):
    m.setenv("MOONRAKER_URL", B); m.setenv("MOONRAKER_FALLBACK_URL", "")


def _mock_reads():
    respx.get(f"{B}/printer/info").mock(return_value=httpx.Response(200, json=READY))
    respx.get(url__regex=rf"{B}/printer/objects/query.*").mock(return_value=httpx.Response(200, json=STATUS))


@respx.mock
async def test_set_temperature_without_confirm_previews_and_sends_nothing(monkeypatch):
    _env(monkeypatch); _mock_reads()
    script = respx.post(url__regex=rf"{B}/printer/gcode/script.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    out = await srv.set_temperature("extruder", 210)
    assert out["confirm_required"] is True
    assert out["preview"]["gcode"] == "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=210"
    assert out["preview"]["current_c"] == 25.0
    assert not script.called


@respx.mock
async def test_set_temperature_confirm_sends_gcode(monkeypatch):
    _env(monkeypatch); _mock_reads()
    script = respx.post(url__regex=rf"{B}/printer/gcode/script.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    out = await srv.set_temperature("bed", 60, confirm=True)
    assert out["ok"] is True
    assert "HEATER=heater_bed" in str(script.calls.last.request.url) and "TARGET=60" in str(script.calls.last.request.url)


@respx.mock
async def test_set_temperature_refuses_above_ceiling_even_with_confirm(monkeypatch):
    _env(monkeypatch); _mock_reads()
    script = respx.post(url__regex=rf"{B}/printer/gcode/script.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    out = await srv.set_temperature("extruder", 320, confirm=True)
    assert "refused" in out["error"] and not script.called


@respx.mock
async def test_control_refused_when_not_ready(monkeypatch):
    _env(monkeypatch)
    respx.get(f"{B}/printer/info").mock(return_value=httpx.Response(200, json=SHUT))
    respx.get(url__regex=rf"{B}/printer/objects/query.*").mock(return_value=httpx.Response(200, json=STATUS))
    pause = respx.post(f"{B}/printer/print/pause").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    out = await srv.pause_print(confirm=True)
    assert "not 'ready'" in out["error"] and not pause.called


@respx.mock
async def test_pause_resume_cancel_confirm_paths(monkeypatch):
    _env(monkeypatch); _mock_reads()
    routes = {n: respx.post(f"{B}/printer/print/{n}").mock(return_value=httpx.Response(200, json={"result": "ok"}))
              for n in ("pause", "resume", "cancel")}
    prev = await srv.cancel_print()
    assert prev["confirm_required"] and prev["preview"]["filename"] == "a.gcode" and prev["preview"]["progress_percent"] == 40
    assert (await srv.pause_print(confirm=True))["ok"] and routes["pause"].called
    assert (await srv.resume_print(confirm=True))["ok"] and routes["resume"].called
    assert (await srv.cancel_print(confirm=True))["ok"] and routes["cancel"].called


@respx.mock
async def test_tune_live_preview_lists_gcode_and_confirm_sends_each_line(monkeypatch):
    _env(monkeypatch); _mock_reads()
    script = respx.post(url__regex=rf"{B}/printer/gcode/script.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    prev = await srv.tune_live(pressure_advance=0.04, fan_percent=50)
    assert prev["preview"]["gcode"] == ["SET_PRESSURE_ADVANCE ADVANCE=0.04", "M106 S128"]
    assert not script.called
    out = await srv.tune_live(pressure_advance=0.04, fan_percent=50, confirm=True)
    assert out["ok"] and script.call_count == 2
    assert (await srv.tune_live())["error"] == "nothing_to_tune"
    assert "refused" in (await srv.tune_live(z_offset=5, confirm=True))["error"]


@respx.mock
async def test_send_gcode_and_firmware_restart_and_emergency_stop(monkeypatch):
    _env(monkeypatch)
    respx.get(f"{B}/printer/info").mock(return_value=httpx.Response(200, json=SHUT))
    script = respx.post(url__regex=rf"{B}/printer/gcode/script.*").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    fr = respx.post(f"{B}/printer/firmware_restart").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    es = respx.post(f"{B}/printer/emergency_stop").mock(return_value=httpx.Response(200, json={"result": "ok"}))
    # send_gcode needs ready -> refused while shutdown
    assert "not 'ready'" in (await srv.send_gcode("M117 hi", confirm=True))["error"] and not script.called
    # firmware_restart is the fix for shutdown, so it must NOT require ready; still two-phase
    prev = await srv.firmware_restart()
    assert prev["confirm_required"] and "MCU" in prev["preview"]["klippy_message"]
    assert (await srv.firmware_restart(confirm=True))["ok"] and fr.called
    # emergency_stop acts immediately, no confirm parameter
    assert (await srv.emergency_stop())["ok"] and es.called
