"""Always-on capture: hold a Moonraker websocket, record every finished print into the
shared outcome store, and backfill from REST history on every (re)connect so nothing is
missed while this service was down. Runs as the klipper-mcp-capture systemd service."""
from __future__ import annotations
import asyncio, json, logging, sys
import websockets
from .client import MoonrakerClient
from .config import load_config
from . import outcomes

log = logging.getLogger("klipper_mcp.capture")

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
    job = ev.get("job") or {}
    if ev.get("action") != "finished" or job.get("status") not in FINISHED_STATUSES:
        return None
    rid = outcomes.record_outcome(job, printer_id)
    log.info("recorded finished job %s (%s) -> row %s", job.get("job_id"), job.get("status"), rid)
    return rid


async def backfill(client: MoonrakerClient, printer_id: str) -> int:
    since = outcomes.last_job_end_time()
    jobs = await client.history_list(limit=100, since=since if since > 0 else None)
    n = 0
    for job in jobs:
        if job.get("status") not in FINISHED_STATUSES:
            continue
        end = job.get("end_time") or 0
        if end <= since:
            continue
        outcomes.record_outcome(job, printer_id)
        n += 1
    if n:
        log.info("backfilled %d finished job(s) since %s", n, since)
    return n


async def run(stop: asyncio.Event | None = None) -> None:
    cfg = load_config()
    delay = 2.0
    while not (stop and stop.is_set()):
        try:
            async with MoonrakerClient(cfg) as c:
                await c.server_info()          # resolves the working base URL (fallback aware)
                await backfill(c, cfg.printer_id)
                url = ws_url(c.base_url)
            log.info("connecting %s", url)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                delay = 2.0
                await ws.send(json.dumps({"jsonrpc": "2.0", "method": "server.connection.identify",
                                          "params": {"client_name": "klipper-mcp-capture", "version": "0.1.0",
                                                     "type": "agent", "url": "https://github.com/MaxEllis/klipper-mcp"},
                                          "id": 1}))
                async for raw in ws:
                    handle_message(raw, cfg.printer_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a daemon must survive anything and retry
            log.warning("capture loop error: %s; retrying in %.0fs", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
