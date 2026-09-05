import json
import httpx, respx
from klipper_mcp import capture, outcomes as oc
from klipper_mcp.client import MoonrakerClient
from klipper_mcp.config import Config

B = "http://x:7125"
JOB = {"job_id": "000092", "filename": "cube.gcode", "status": "completed", "end_time": 200.0,
       "total_duration": 10.0, "metadata": {"filament_weight_total": 1.5}}


def _frame(action, job):
    return json.dumps({"jsonrpc": "2.0", "method": "notify_history_changed",
                       "params": [{"action": action, "job": job}]})


def test_handle_finished_records(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    rid = capture.handle_message(_frame("finished", JOB), "swx2")
    assert rid is not None
    assert oc.recall(limit=1)[0]["job_id"] == "000092"


def test_handle_ignores_added_and_other_methods_and_garbage(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    assert capture.handle_message(_frame("added", {**JOB, "status": "in_progress"}), "swx2") is None
    assert capture.handle_message(json.dumps({"jsonrpc": "2.0", "method": "notify_status_update", "params": [{}]}), "swx2") is None
    assert capture.handle_message("not json", "swx2") is None
    assert oc.is_available() is False  # nothing was written


def test_ws_url():
    assert capture.ws_url("http://klipper.local:7125") == "ws://klipper.local:7125/websocket"
    assert capture.ws_url("https://k:443") == "wss://k:443/websocket"


def test_handle_message_odd_but_valid_json_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    # params[0] is not a dict at all
    frame = json.dumps({"jsonrpc": "2.0", "method": "notify_history_changed", "params": ["x"]})
    assert capture.handle_message(frame, "swx2") is None
    # job is a string, not a dict
    frame2 = _frame("finished", "not-a-job")
    assert capture.handle_message(frame2, "swx2") is None
    assert oc.is_available() is False  # nothing was ever written


def test_should_warn_dedupes_repeated_error():
    assert capture._should_warn("boom", None) is True
    assert capture._should_warn("boom", "boom") is False
    assert capture._should_warn("bang", "boom") is True


async def test_after_disconnect_doubles_and_caps(monkeypatch):
    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(capture.asyncio, "sleep", fake_sleep)
    assert await capture._after_disconnect(2.0) == 4.0
    assert await capture._after_disconnect(45.0) == 60.0
    assert await capture._after_disconnect(60.0) == 60.0
    assert calls == [2.0, 45.0, 60.0]


@respx.mock
async def test_backfill_records_only_newer_finished_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    oc.record_outcome({**JOB, "job_id": "000090", "end_time": 100.0})
    route = respx.get(url__regex=rf"{B}/server/history/list.*").mock(return_value=httpx.Response(200, json={
        "result": {"count": 3, "jobs": [
            {**JOB, "job_id": "000093", "status": "in_progress", "end_time": None},
            {**JOB, "job_id": "000092", "end_time": 200.0},
            {**JOB, "job_id": "000090", "end_time": 100.0},
        ]}}))
    async with MoonrakerClient(Config(B, None, 5, "swx2")) as c:
        n = await capture.backfill(c, "swx2")
    assert n == 1
    ids = sorted(r["job_id"] for r in oc.recall(limit=10))
    assert ids == ["000090", "000092"]
    assert "since=100" in str(route.calls.last.request.url)
