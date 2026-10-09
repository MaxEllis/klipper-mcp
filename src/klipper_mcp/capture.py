"""Always-on capture: hold a Moonraker websocket, record every finished print into the
shared outcome store, and backfill from REST history on every (re)connect so nothing is
missed while this service was down. Runs as the klipper-mcp-capture systemd service."""
from __future__ import annotations
import asyncio, importlib.metadata, json, logging, sqlite3, sys
import websockets
from .client import MoonrakerClient
from .config import load_config
from .errors import NotConfigured
from . import outcomes

log = logging.getLogger("klipper_mcp.capture")

try:
    _VERSION = importlib.metadata.version("klipper-mcp")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.0.0"

FINISHED_STATUSES = frozenset({"completed", "cancelled", "error", "klippy_shutdown",
                               "klippy_disconnect", "interrupted"})


def ws_url(base_url: str) -> str:
    scheme = "wss" if base_url.startswith("https://") else "ws"
    host = base_url.split("://", 1)[1].rstrip("/")
    return f"{scheme}://{host}/websocket"


def handle_message(raw: str, printer_id: str) -> int | None:
    try:
        msg = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("method") != "notify_history_changed":
        return None
    params = msg.get("params") or [{}]
    ev = params[0] if isinstance(params, list) and params else {}
    if not isinstance(ev, dict):
        ev = {}
    job = ev.get("job")
    if not isinstance(job, dict):
        return None
    if ev.get("action") != "finished" or job.get("status") not in FINISHED_STATUSES:
        return None
    rid = outcomes.record_outcome(job, printer_id)
    log.info("recorded finished job %s (%s) -> row %s", job.get("job_id"), job.get("status"), rid)
    return rid


BACKFILL_LIMIT = 100
_WARNED_JOBS: set[str] = set()  # jobs already reported as unrecordable: a reconnect must not repeat the warning


async def backfill(client: MoonrakerClient, printer_id: str) -> int:
    """Record every finished job among Moonraker's latest BACKFILL_LIMIT. Catching up from the newest
    stored job would skip an older one the recorder missed whenever something else (orcaslicer-mcp's
    list_print_history) had already stored a newer one; record_outcome is idempotent on job_id and only
    fills gaps, so checking them all is safe. A job that cannot be recorded (odd metadata, say) is
    skipped with one warning, so one bad job never stops the catch-up (which runs before the websocket
    opens, so it would stop live recording on every reconnect); a locked or unwritable store still
    raises. An entry that is not a job object, has no job_id or has an unreadable end time is skipped
    without a warning. Returns how many finished jobs it recorded or confirmed."""
    jobs = await client.history_list(limit=BACKFILL_LIMIT)
    checked = 0
    for job in reversed(jobs):  # Moonraker answers newest first; the jobs finished oldest first
        # Not a job object, or no id: skip it. record_outcome dedupes on job_id, so an entry without
        # one would be inserted again on every reconnect.
        if not isinstance(job, dict) or not job.get("job_id"):
            continue
        if job.get("status") not in FINISHED_STATUSES:
            continue
        try:
            end = float(job.get("end_time") or 0)
        except (TypeError, ValueError, OverflowError):  # OverflowError: a JSON integer beyond float range
            continue
        if end <= 0:
            continue
        try:
            outcomes.record_outcome(job, printer_id)
        except sqlite3.OperationalError:
            raise  # locked or unwritable store: every job would fail, so let the run loop retry
        except Exception as e:  # noqa: BLE001 - one bad job must not abort the catch-up
            key = str(job.get("job_id"))
            level = logging.DEBUG if key in _WARNED_JOBS else logging.WARNING
            _WARNED_JOBS.add(key)
            log.log(level, "backfill skipped job %s: it could not be recorded (%s: %s)", key, type(e).__name__, e)
            continue
        checked += 1
    log.info("backfill checked %d finished job(s) among the latest %d in history", checked, len(jobs))
    return checked


def _should_warn(err: str, last_err: str | None) -> bool:
    """True the first time a given error string is seen (or when it changes from the last
    one); False for a repeat, so a persistent failure logs once at WARNING and then only at
    DEBUG instead of flooding the log every retry."""
    return err != last_err


async def _after_disconnect(delay: float) -> float:
    """Sleep out the current backoff delay after a disconnect (clean or errored),
    then return the next (doubled, capped) delay. Isolated so it can be unit-tested
    without a real websocket."""
    await asyncio.sleep(delay)
    return min(delay * 2, 60.0)


async def run(stop: asyncio.Event | None = None) -> None:
    cfg = load_config()
    delay = 2.0
    last_err: str | None = None
    while not (stop and stop.is_set()):
        try:
            async with MoonrakerClient(cfg) as c:
                await c.server_info()          # resolves the working base URL (fallback aware)
                await backfill(c, cfg.printer_id)
                url = ws_url(c.base_url)
            log.info("connecting %s", url)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                delay = 2.0
                last_err = None
                await ws.send(json.dumps({"jsonrpc": "2.0", "method": "server.connection.identify",
                                          "params": {"client_name": "klipper-mcp-capture", "version": _VERSION,
                                                     "type": "agent", "url": "https://github.com/MaxEllis/klipper-mcp"},
                                          "id": 1}))
                async for raw in ws:
                    handle_message(raw, cfg.printer_id)
            # The websocket closed without raising (e.g. a clean server-side close,
            # code 1000 on a Moonraker restart). Falling out of the read loop is still
            # a disconnect -- never spin straight back into reconnecting.
            log.warning("websocket closed; reconnecting in %.0fs", delay)
            delay = await _after_disconnect(delay)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a daemon must survive anything and retry
            err = str(e)
            if _should_warn(err, last_err):
                log.warning("capture loop error: %s; retrying in %.0fs", err, delay)
            else:
                log.debug("capture loop error (repeat): %s; retrying in %.0fs", err, delay)
            last_err = err
            delay = await _after_disconnect(delay)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    except NotConfigured as e:
        log.error("%s", e)
        sys.exit(2)


if __name__ == "__main__":
    main()
