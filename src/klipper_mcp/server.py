from __future__ import annotations
from pathlib import Path
import importlib.metadata
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from .config import load_config
from .client import MoonrakerClient
from .errors import ApiError, Refused, PrinterNotReady
from . import gate
from . import outcomes
from .status import summarize_status, STATUS_OBJECTS

try:
    _VERSION = importlib.metadata.version("klipper-mcp")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.0.0"

mcp = MCPServer("klipper", version=_VERSION)

RESULT_MAP = {"completed": "success", "cancelled": "cancelled"}  # everything else -> "error"


def _client() -> MoonrakerClient:
    return MoonrakerClient(load_config())


def _err(e: ApiError) -> dict:
    return {"error": str(e)}


def summarize_job(job: dict) -> dict:
    meta = job.get("metadata") or {}
    dur = job.get("total_duration")
    return {
        "job_id": job.get("job_id"),
        "filename": job.get("filename"),
        "result": RESULT_MAP.get(job.get("status"), "error"),
        "moonraker_status": job.get("status"),
        "ended_at": job.get("end_time"),
        "duration_min": None if dur is None else int(round(dur / 60)),
        "filament_g": None if meta.get("filament_weight_total") is None else round(meta["filament_weight_total"], 1),
        "layer_height": meta.get("layer_height"),
        "filament_name": meta.get("filament_name"),
    }


@mcp.tool()
async def get_printer_status() -> dict:
    """Live printer state in one call: Klipper state (ready/shutdown/error + message), current job
    (state, file, progress, durations), extruder and bed actual/target temps, fan, pressure advance,
    live Z offset, speed/flow factors, toolhead position. Read-only. Use this before any control."""
    try:
        async with _client() as c:
            return summarize_status(await c.objects_query(STATUS_OBJECTS))
    except ApiError as e:
        return _err(e)


@mcp.tool()
async def get_printer_info() -> dict:
    """Klipper host info: state and the full state message (e.g. why it is shut down and how to
    recover), Klipper version, hostname. Read-only."""
    try:
        async with _client() as c:
            info = await c.printer_info()
        return {"state": info.get("state"), "message": (info.get("state_message") or "").strip(),
                "software_version": info.get("software_version"), "hostname": info.get("hostname")}
    except ApiError as e:
        return _err(e)


@mcp.tool()
async def list_print_history(limit: int = 10) -> dict:
    """Recent print jobs from Moonraker's history, newest first: result (success/cancelled/error),
    duration, filament grams, layer height, filament preset. Read-only."""
    try:
        async with _client() as c:
            jobs = await c.history_list(limit=max(1, min(limit, 100)))
        return {"count": len(jobs), "jobs": [summarize_job(j) for j in jobs]}
    except ApiError as e:
        return _err(e)


@mcp.tool()
async def list_gcode_files(limit: int = 50) -> dict:
    """G-code files staged on the printer (Moonraker 'gcodes' root), newest first. Read-only."""
    try:
        async with _client() as c:
            files = await c.files_list("gcodes")
        files = sorted(files, key=lambda f: f.get("modified", 0), reverse=True)
        shown = files[:max(1, limit)]
        return {"count": len(shown), "total": len(files),
                "files": [{"path": f.get("path"), "size": f.get("size"), "modified": f.get("modified")}
                          for f in shown]}
    except ApiError as e:
        return _err(e)


_HEATERS = {"extruder": "extruder", "bed": "heater_bed", "heater_bed": "heater_bed"}
_GCODE_SUFFIXES = {".gcode", ".gco", ".g", ".ufp"}


async def _ready_and_status(c) -> tuple[dict, dict]:
    """Return (printer_info, status_summary); raise PrinterNotReady if Klipper is not ready."""
    info = await c.printer_info()
    gate.require_ready(info)
    return info, summarize_status(await c.objects_query(STATUS_OBJECTS))


def _job_preview(st: dict) -> dict:
    return {"filename": st["job"]["filename"], "job_state": st["job"]["state"],
            "progress_percent": st["job"]["progress_percent"]}


@mcp.tool()
async def set_temperature(heater: str, target: float, confirm: bool = False) -> dict:
    """Set a heater target. heater: 'extruder' or 'bed'. Hard ceilings: extruder 300C, bed 110C.
    Refused unless Klipper is ready. TWO-PHASE: without confirm=true this returns a preview and
    changes nothing; ask the user, then call again with confirm=true."""
    try:
        h = _HEATERS.get(heater)
        if not h:
            return {"error": f"unknown heater '{heater}' (use 'extruder' or 'bed')"}
        gate.check_bounds(**({"extruder_c": target} if h == "extruder" else {"bed_c": target}))
        gcode = f"SET_HEATER_TEMPERATURE HEATER={h} TARGET={float(target):g}"
        async with _client() as c:
            _, st = await _ready_and_status(c)
            cur = st["temps"]["extruder" if h == "extruder" else "bed"]["actual"]
            if not confirm:
                return gate.confirm_required("set_temperature", {"heater": h, "target_c": target,
                                                                 "current_c": cur, "gcode": gcode})
            await c.gcode_script(gcode)
        return {"ok": True, "action": "set_temperature", "heater": h, "target_c": target}
    except (Refused, PrinterNotReady, ApiError) as e:
        return _err(e)


_JOB_METHODS = {"pause_print": "print_pause", "resume_print": "print_resume", "cancel_print": "print_cancel"}


async def _job_control(action: str, confirm: bool) -> dict:
    try:
        async with _client() as c:
            _, st = await _ready_and_status(c)
            if not confirm:
                return gate.confirm_required(action, _job_preview(st))
            await getattr(c, _JOB_METHODS[action])()
        return {"ok": True, "action": action, "was": _job_preview(st)}
    except (PrinterNotReady, ApiError) as e:
        return _err(e)


@mcp.tool()
async def pause_print(confirm: bool = False) -> dict:
    """Pause the running print. TWO-PHASE: without confirm=true this returns a preview and changes
    nothing; ask the user, then call again with confirm=true."""
    return await _job_control("pause_print", confirm)


@mcp.tool()
async def resume_print(confirm: bool = False) -> dict:
    """Resume a paused print. TWO-PHASE: without confirm=true this returns a preview and changes
    nothing; ask the user, then call again with confirm=true."""
    return await _job_control("resume_print", confirm)


@mcp.tool()
async def cancel_print(confirm: bool = False) -> dict:
    """Cancel the running print (irreversible). TWO-PHASE: without confirm=true this returns a
    preview and changes nothing; ask the user, then call again with confirm=true."""
    return await _job_control("cancel_print", confirm)


@mcp.tool()
async def tune_live(pressure_advance: float | None = None, z_offset: float | None = None,
                    flow_percent: float | None = None, fan_percent: float | None = None,
                    confirm: bool = False) -> dict:
    """Live-tune the running (or next) print: pressure_advance (0..1), z_offset in mm (-2..2, absolute
    baby-step offset), flow_percent (50..150), fan_percent (0..100). Sends each provided value as its
    own gcode line, in sequence, under a single confirmation. Refused unless Klipper is ready.
    TWO-PHASE: without confirm=true this returns a preview (the exact gcode lines and current values)
    and changes nothing; ask the user, then call again with confirm=true."""
    try:
        lines = gate.tune_gcode(pressure_advance, z_offset, flow_percent, fan_percent)
        if not lines:
            return {"error": "nothing_to_tune"}
        gate.check_bounds(pressure_advance=pressure_advance, z_offset=z_offset,
                          flow_percent=flow_percent, fan_percent=fan_percent)
        async with _client() as c:
            _, st = await _ready_and_status(c)
            current = {"pressure_advance": st["pressure_advance"], "z_offset": st["z_offset"],
                       "flow_factor": st["flow_factor"], "fan_percent": st["fan_percent"]}
            if not confirm:
                return gate.confirm_required("tune_live", {"gcode": lines, "current": current})
            for i, line in enumerate(lines):
                try:
                    await c.gcode_script(line)
                except ApiError as e:
                    return {"error": str(e), "sent": lines[:i], "not_sent": lines[i:]}
        return {"ok": True, "action": "tune_live", "sent": lines}
    except (Refused, PrinterNotReady, ApiError) as e:
        return _err(e)


@mcp.tool()
async def send_gcode(script: str, confirm: bool = False) -> dict:
    """Send raw G-code / a Klipper macro, VERBATIM: no rewriting. Multiple lines are allowed and all
    execute under the single confirmation. The numeric ceilings enforced by set_temperature/tune_live
    do NOT apply on this path; the preview shows the exact bytes that will be sent, so review it
    carefully. The general actuator behind the specific tools; prefer those. Refused unless Klipper
    is ready. TWO-PHASE: without confirm=true this returns a preview and changes nothing; ask the
    user, then call again with confirm=true."""
    try:
        script = script.strip()
        if not script:
            return {"error": "empty_script"}
        async with _client() as c:
            _, st = await _ready_and_status(c)
            if not confirm:
                return gate.confirm_required("send_gcode", {"gcode": script, **_job_preview(st)})
            await c.gcode_script(script)
        return {"ok": True, "action": "send_gcode", "sent": script}
    except (PrinterNotReady, ApiError) as e:
        return _err(e)


@mcp.tool()
async def firmware_restart(confirm: bool = False) -> dict:
    """FIRMWARE_RESTART: recover Klipper from a shutdown state (e.g. after power-cycling the printer).
    Does NOT require Klipper to be ready (it is the fix for not-ready). TWO-PHASE: without confirm=true
    this returns a preview (the current state message) and changes nothing; ask the user, then call
    again with confirm=true."""
    try:
        async with _client() as c:
            info = await c.printer_info()
            if not confirm:
                return gate.confirm_required("firmware_restart", {
                    "klippy_state": info.get("state"), "klippy_message": (info.get("state_message") or "").strip()})
            await c.firmware_restart()
        return {"ok": True, "action": "firmware_restart", "was_state": info.get("state")}
    except ApiError as e:
        return _err(e)


@mcp.tool()
async def emergency_stop() -> dict:
    """EMERGENCY STOP: immediately halts the printer (Klipper enters shutdown; heaters and motors off).
    Acts at once, no preview, because a delay would defeat its purpose. Recover with firmware_restart."""
    try:
        async with _client() as c:
            await c.emergency_stop()
        return {"ok": True, "action": "emergency_stop"}
    except ApiError as e:
        return _err(e)


@mcp.tool()
async def start_print(path: str, confirm: bool = False) -> dict:
    """Start a print. path = a LOCAL gcode file on this server (e.g. one saved by orcaslicer-mcp's
    save_gcode; it is uploaded to the printer under its basename) OR a filename already staged on
    the printer, including in a subdirectory (see list_gcode_files; no upload). A bare name that
    also exists as a local file in this server's working directory is treated as local and
    uploaded; the preview's upload_needed / overwrites_existing fields show which. TWO-PHASE:
    without confirm=true this returns a preview and changes nothing; ask the user, then call
    again with confirm=true. Refused unless Klipper is ready and idle."""
    try:
        local = Path(path)
        is_local = local.exists() and local.is_file()
        filename = local.name if is_local else Path(path).name
        if is_local and local.suffix.lower() not in _GCODE_SUFFIXES:
            return {"error": "not_gcode", "path": path}
        async with _client() as c:
            _, st = await _ready_and_status(c)
            if st["job"]["state"] in ("printing", "paused"):
                return {"error": "printer_busy", "current": _job_preview(st)}
            on_pi = {f.get("path") for f in await c.files_list("gcodes")}
            if not is_local:
                if path not in on_pi:
                    return {"error": "file_not_found", "path": path,
                            "hint": "not a local file and not on the printer; see list_gcode_files"}
                filename = path
            overwrites_existing = is_local and filename in on_pi
            preview = {"filename": filename, "upload_needed": is_local,
                       "overwrites_existing": overwrites_existing,
                       "size_bytes": local.stat().st_size if is_local else None,
                       "klippy_state": st["klippy"]["state"], "job_state": st["job"]["state"]}
            if not confirm:
                return gate.confirm_required("start_print", preview)
            if is_local:
                await c.upload_gcode(str(local), filename)
                try:
                    await c.print_start(filename)
                except ApiError as e:
                    return {"error": str(e), "uploaded": True, "filename": filename}
            else:
                await c.print_start(filename)
        return {"ok": True, "action": "start_print", "filename": filename, "uploaded": is_local,
                "overwrites_existing": overwrites_existing}
    except (PrinterNotReady, ApiError) as e:
        return _err(e)


@mcp.tool()
def record_verdict(verdict: str, gcode_filename: str | None = None) -> dict:
    """Attach your quality judgement to a finished print in the shared outcome memory, e.g. 'warped',
    'stringing', 'clean', 'layer shift at 40%'. Defaults to the most recently finished print;
    pass gcode_filename to target another. This is what lets the slicer learn from real results."""
    return outcomes.set_verdict(verdict, gcode_filename)


_TOOL_ANNOTATIONS: dict[str, tuple[str, bool, bool]] = {
    # name: (title, read_only, destructive)
    "get_printer_status": ("Get live printer status", True, False),
    "get_printer_info": ("Get Klipper host info", True, False),
    "list_print_history": ("List print history", True, False),
    "list_gcode_files": ("List G-code files on printer", True, False),
    "set_temperature": ("Set heater temperature", False, True),
    "pause_print": ("Pause print", False, True),
    "resume_print": ("Resume print", False, True),
    "cancel_print": ("Cancel print", False, True),
    "tune_live": ("Live-tune PA / Z / flow / fan", False, True),
    "send_gcode": ("Send raw G-code", False, True),
    "firmware_restart": ("Firmware restart", False, True),
    "emergency_stop": ("Emergency stop", False, True),
    "start_print": ("Start print (upload + start)", False, True),
    "record_verdict": ("Record print verdict", False, False),
}


def _apply_annotations() -> None:
    for name, tool in mcp._tool_manager._tools.items():
        title, read_only, destructive = _TOOL_ANNOTATIONS[name]
        tool.annotations = ToolAnnotations(title=title, readOnlyHint=read_only,
                                           destructiveHint=None if read_only else destructive)


_apply_annotations()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
