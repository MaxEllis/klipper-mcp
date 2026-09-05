"""Server-enforced two-phase confirmation and hard bounds for every control tool.

Why server-side: homeserver Claude sessions run with bypassPermissions, so MCP destructive
annotations never produce a host prompt here. Rule 3 (confirm every destructive op, no batching)
is therefore enforced HERE: without confirm=True a control tool returns a preview and does nothing.
"""
from __future__ import annotations
from .errors import Refused, PrinterNotReady

# Ceilings from printer.cfg (extruder max_temp 300) and sane bed/PA/offset/flow/fan ranges.
LIMITS = {"extruder_c": (0, 300), "bed_c": (0, 110), "pressure_advance": (0.0, 1.0),
          "z_offset": (-2.0, 2.0), "flow_percent": (50, 150), "fan_percent": (0, 100)}


def confirm_required(action: str, preview: dict) -> dict:
    return {"confirm_required": True, "action": action, "preview": preview,
            "how": ("Nothing was changed. Show the user this exact preview, get their explicit go-ahead, "
                    "then call the same tool again with confirm=true. One action per confirmation.")}


def check_bounds(**kw) -> None:
    for name, val in kw.items():
        if val is None:
            continue
        lo, hi = LIMITS[name]
        if not (lo <= float(val) <= hi):
            raise Refused(f"{name}={val} is outside the allowed range {lo}..{hi}; refused")


def tune_gcode(pressure_advance=None, z_offset=None, flow_percent=None, fan_percent=None) -> list[str]:
    lines: list[str] = []
    if pressure_advance is not None:
        lines.append(f"SET_PRESSURE_ADVANCE ADVANCE={float(pressure_advance):g}")
    if z_offset is not None:
        lines.append(f"SET_GCODE_OFFSET Z={float(z_offset):g} MOVE=1")
    if flow_percent is not None:
        lines.append(f"M221 S{int(round(flow_percent))}")
    if fan_percent is not None:
        lines.append(f"M106 S{int(round(float(fan_percent) * 255 / 100))}")
    return lines


def require_ready(info: dict) -> None:
    state = info.get("state")
    if state != "ready":
        msg = (info.get("state_message") or "").strip().splitlines()
        raise PrinterNotReady(f"Klipper state is '{state}', not 'ready'. {msg[0] if msg else ''}".strip())
