import json
import sqlite3
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


BAD_JOB = {**JOB, "job_id": "00F0A2", "end_time": 200.0, "metadata": "not an object"}  # record_outcome raises on it


@respx.mock
async def test_backfill_goes_on_past_a_job_that_cannot_be_recorded(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    monkeypatch.setattr(capture, "_WARNED_JOBS", set())
    with pytest.raises(AttributeError):  # the premise: this job really makes record_outcome raise
        oc.record_outcome(BAD_JOB)
    _history([{**JOB, "job_id": "00F0A3", "end_time": 300.0}, BAD_JOB, {**JOB, "job_id": "00F0A1", "end_time": 100.0}])
    with caplog.at_level("INFO", logger="klipper_mcp.capture"):
        async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
            n = await capture.backfill(c, "test-printer")
    assert sorted(r["job_id"] for r in oc.recall(limit=10)) == ["00F0A1", "00F0A3"]  # both neighbours recorded
    assert n == 2  # the two it could record
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1 and "00F0A2" in warnings[0]
    assert "checked 2 finished job(s)" in caplog.text


@respx.mock
async def test_a_job_that_cannot_be_recorded_is_warned_about_once_across_reconnects(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    monkeypatch.setattr(capture, "_WARNED_JOBS", set())
    _history([BAD_JOB, {**JOB, "job_id": "00F0A1", "end_time": 100.0}])
    with caplog.at_level("DEBUG", logger="klipper_mcp.capture"):
        async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
            await capture.backfill(c, "test-printer")
            await capture.backfill(c, "test-printer")  # the next (re)connect
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "00F0A2" in r.getMessage()]
    assert len(warnings) == 1
    assert any(r.levelname == "DEBUG" and "00F0A2" in r.getMessage() for r in caplog.records)  # still traceable


@respx.mock
async def test_backfill_skips_entries_that_are_not_job_objects(monkeypatch, tmp_path):
    # the pre-checks used to call job.get on whatever the printer sent, so one odd entry stopped the catch-up
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    _history([{**JOB, "job_id": "00F0A3", "end_time": 300.0}, "not an object", None, ["a", "list"], 7,
              {**JOB, "job_id": "00F0A1", "end_time": 100.0}])
    async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
        n = await capture.backfill(c, "test-printer")
    assert n == 2 and sorted(r["job_id"] for r in oc.recall(limit=10)) == ["00F0A1", "00F0A3"]


@respx.mock
async def test_backfill_skips_an_end_time_too_large_to_read_as_a_number(monkeypatch, tmp_path):
    # a JSON integer beyond float range makes float() raise OverflowError, which is neither a TypeError nor a ValueError
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    _history([{**JOB, "job_id": "00F0A3", "end_time": 10 ** 400}, {**JOB, "job_id": "00F0A2", "end_time": 200.0}])
    async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
        n = await capture.backfill(c, "test-printer")
    assert n == 1 and [r["job_id"] for r in oc.recall(limit=10)] == ["00F0A2"]


@respx.mock
async def test_backfill_leaves_out_a_finished_job_without_a_job_id_instead_of_inserting_it_every_time(monkeypatch, tmp_path):
    # record_outcome dedupes on job_id, so an entry without one would be inserted again on every reconnect
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    no_id = {k: v for k, v in JOB.items() if k != "job_id"}
    _history([{**no_id, "end_time": 300.0}, {**JOB, "job_id": None, "end_time": 250.0},
              {**JOB, "job_id": "", "end_time": 220.0}, {**JOB, "job_id": "00F0A1", "end_time": 100.0}])
    async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
        first = await capture.backfill(c, "test-printer")
        second = await capture.backfill(c, "test-printer")  # the next (re)connect
    assert first == second == 1
    assert [r["job_id"] for r in oc.recall(limit=10)] == ["00F0A1"]


@respx.mock
async def test_backfill_still_raises_when_the_store_is_locked_or_unwritable(monkeypatch, tmp_path):
    # a store problem would hit every job, and the run loop's retry is the right response to it
    monkeypatch.setenv("PRINT_OUTCOMES_DIR", str(tmp_path))
    monkeypatch.setattr(capture, "_WARNED_JOBS", set())
    seen = []

    def locked(job, printer_id):
        seen.append(job["job_id"])
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(capture.outcomes, "record_outcome", locked)
    _history([{**JOB, "job_id": "00F0A2", "end_time": 200.0}, {**JOB, "job_id": "00F0A1", "end_time": 100.0}])
    async with MoonrakerClient(Config(B, None, 5, "test-printer")) as c:
        with pytest.raises(sqlite3.OperationalError):
            await capture.backfill(c, "test-printer")
    assert seen == ["00F0A1"]  # it stopped at the first job: no point asking the locked store again


def test_main_exits_with_a_clear_message_when_unconfigured(monkeypatch, caplog):
    monkeypatch.delenv("MOONRAKER_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        capture.main()
    assert exc.value.code == 2
    assert "MOONRAKER_URL is not set" in caplog.text
