from __future__ import annotations
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from .config import load_config
from .client import MoonrakerClient
from .errors import ApiError
from .status import summarize_status, STATUS_OBJECTS

mcp = FastMCP("klipper")

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
        return {"count": len(files),
                "files": [{"path": f.get("path"), "size": f.get("size"), "modified": f.get("modified")}
                          for f in files[:max(1, limit)]]}
    except ApiError as e:
        return _err(e)


_TOOL_ANNOTATIONS: dict[str, tuple[str, bool, bool]] = {
    # name: (title, read_only, destructive)
    "get_printer_status": ("Get live printer status", True, False),
    "get_printer_info": ("Get Klipper host info", True, False),
    "list_print_history": ("List print history", True, False),
    "list_gcode_files": ("List G-code files on printer", True, False),
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
