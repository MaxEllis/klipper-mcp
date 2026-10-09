import json
import httpx, pytest, respx
from klipper_mcp import capture, outcomes as oc
from klipper_mcp.client import MoonrakerClient
from klipper_mcp.config import Config

B = "http://x:7125"
JOB = {"job_id": "00F0A2", "filename": "cube.gcode", "status": "completed", "end_time": 200.0,
       "total_duration": 10.0, "metadata": {"filament_weight_total": 1.5}}


def _frame(action, job):
    return json.dumps({"jsonrpc": "2.0", "method": "notify_history_changed",
                       "params": [{"action": action, "job": job}]})


def test_handle_finished_records(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    rid = capture.handle_message(_frame("finished", JOB), "test-printer")
    assert rid is not None
    assert oc.recall(limit=1)[0]["job_id"] == "00F0A2"


def test_handle_ignores_added_and_other_methods_and_garbage(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    assert capture.handle_message(_frame("added", {**JOB, "status": "in_progress"}), "test-printer") is None
    assert capture.handle_message(json.dumps({"jsonrpc": "2.0", "method": "notify_status_update", "params": [{}]}), "test-printer") is None
    assert capture.handle_message("not json", "test-printer") is None
    assert oc.is_available() is False  # nothing was written


def test_ws_url():
    assert capture.ws_url("http://printer.local:7125") == "ws://printer.local:7125/websocket"
    assert capture.ws_url("https://k:443") == "wss://k:443/websocket"


def test_handle_message_odd_but_valid_json_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    # params[0] is not a dict at all
    frame = json.dumps({"jsonrpc": "2.0", "method": "notify_history_changed", "params": ["x"]})
    assert capture.handle_message(frame, "test-printer") is None
    # job is a string, not a dict
    frame2 = _frame("finished", "not-a-job")
    assert capture.handle_message(frame2, "test-printer") is None
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


def _history(jobs):
    return respx.get(url__regex=rf"{B}/server/history/list.*").mock(
        return_value=httpx.Response(200, json={"result": {"count": len(jobs), "jobs": jobs}}))


@respx.mock
async def test_backfill_checks_the_latest_hundred_and_records_each_finished_job_once(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    oc.record_outcome({**JOB, "job_id": "00F0A1", "end_time": 100.0})
    route = _history([
        {**JOB, "job_id": "00F0A3", "status": "in_progress", "end_time": None},
        {**JOB, "job_id": "00F0A2", "end_time": 200.0},
        {**JOB, "job_id": "00F0A1", "end_time": 100.0},
    ])
    async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
        n = await capture.backfill(c, "test-printer")
    assert n == 2  # the two finished jobs it checked; the running one is not finished
    assert sorted(r["job_id"] for r in oc.recall(limit=10)) == ["00F0A1", "00F0A2"]  # the first was not added twice
    url = str(route.calls.last.request.url)
    assert "limit=100" in url and "since" not in url  # no catch-up point: the whole recent window


@respx.mock
async def test_backfill_records_an_older_job_when_a_newer_one_is_already_stored(monkeypatch, tmp_path):
    # list_print_history can have written the newest job already; catching up from MAX(printed_at)
    # would then skip the older job the recorder missed while it was down.
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    oc.record_outcome({**JOB, "job_id": "00F0A3", "end_time": 300.0})
    _history([
        {**JOB, "job_id": "00F0A3", "end_time": 300.0},
        {**JOB, "job_id": "00F0A2", "end_time": 200.0},
    ])
    async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
        await capture.backfill(c, "test-printer")
    assert sorted(r["job_id"] for r in oc.recall(limit=10)) == ["00F0A2", "00F0A3"]


@respx.mock
async def test_backfill_logs_how_many_it_checked(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    _history([{**JOB, "job_id": "00F0A2", "end_time": 200.0}, {**JOB, "job_id": "00F0A1", "end_time": 100.0}])
    with caplog.at_level("INFO", logger="klipper_mcp.capture"):
        async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
            await capture.backfill(c, "test-printer")
    assert "checked 2 finished job(s)" in caplog.text


@respx.mock
async def test_backfill_skips_a_job_without_a_usable_end_time(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    _history([{**JOB, "job_id": "00F0A3", "end_time": "soon"}, {**JOB, "job_id": "00F0A2", "end_time": None},
              {**JOB, "job_id": "00F0A1", "end_time": 100.0}])
    async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
        n = await capture.backfill(c, "test-printer")
    assert n == 1 and [r["job_id"] for r in oc.recall(limit=10)] == ["00F0A1"]


@respx.mock
async def test_backfill_walks_oldest_first_so_the_earlier_reprint_claims_the_slice(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    slice_id = oc.record_slice("cube.gcode", "cube", "hash-one", {}, printer_id="test-printer", sliced_at=10.0)
    _history([  # newest first, as Moonraker answers
        {**JOB, "job_id": "00F0A5", "start_time": 300.0, "end_time": 400.0},
        {**JOB, "job_id": "00F0A2", "start_time": 100.0, "end_time": 200.0},
    ])
    async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
        await capture.backfill(c, "test-printer")
    assert oc.get(slice_id)["job_id"] == "00F0A2"


def test_main_exits_with_a_clear_message_when_unconfigured(monkeypatch, caplog):
    monkeypatch.delenv("MOONRAKER_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        capture.main()
    assert exc.value.code == 2
    assert "MOONRAKER_URL is not set" in caplog.text
