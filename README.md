# klipper-mcp

Watch and drive a Klipper 3D printer through Moonraker from Claude or any MCP client, and
remember how every print actually turned out.

It talks to Moonraker's HTTP and websocket APIs, so it works with any printer Moonraker
already manages. It does not talk to the printer directly and it does not touch a camera.

## Install

```bash
uv sync
```

This creates `.venv/` with two entry points: `klipper-mcp` (the MCP server) and
`klipper-mcp-capture` (the always-on outcome recorder, see below).

## Configuration

Environment variables, all optional (defaults shown):

| Variable | Default | Purpose |
|---|---|---|
| `MOONRAKER_URL` | `http://klipper.local:7125` | Primary Moonraker endpoint. |
| `MOONRAKER_FALLBACK_URL` | `http://192.168.1.128:7125` | Tried if the primary is unreachable (mDNS drops sometimes; the wired IP does not). Whichever URL answers is remembered for the rest of the process, so later calls skip the dead one; if the remembered URL stops answering, both are tried again. |
| `MOONRAKER_TIMEOUT` | `15` | Seconds allowed for a whole request (read/write phases). |
| `MOONRAKER_CONNECT_TIMEOUT` | `3` | Seconds allowed to connect. Kept short so an mDNS name that no longer resolves fails over to the IP in seconds, not after the full request timeout. |
| `PRINT_OUTCOMES_DIR` | `~/projects/_shared/print-outcomes` | Directory holding `outcomes.db`, the shared print-outcome store. |
| `PRINTER_ID` | `swx2` | Tag written on every recorded row. Only matters once a second printer exists. |

There is one printer behind this server. If you have more than one, run a separate instance
per printer with its own `MOONRAKER_URL` and `PRINTER_ID`.

Auth is whatever Moonraker itself trusts, LAN-only. There is no separate token or login layer
in klipper-mcp.

## Tools

### Read (no confirmation needed, nothing is changed)

- `get_printer_status` - live Klipper state, current job, temps, fan, pressure advance, Z
  offset, speed/flow factors, toolhead position, in one call.
- `get_printer_info` - Klipper state, the full state message (why it's shut down and how to
  recover), software version, hostname.
- `list_print_history` - recent jobs from Moonraker history: result, duration, filament grams,
  layer height, filament preset.
- `list_gcode_files` - files staged on the printer, newest first.

### Control (two-phase, gated)

Every control tool except `emergency_stop` takes a `confirm` argument. Called without
`confirm=true` it changes nothing and returns a preview: the exact action, the exact g-code it
would send, and the printer's current relevant values. The tool must be called again with
`confirm=true` to actually act. This gate is enforced by the server itself, not by the MCP
client, because these sessions run without a host permission prompt - see `src/klipper_mcp/gate.py`.

- `set_temperature` - set an extruder or bed heater target. Hard ceilings: extruder 300C, which
  is `printer.cfg`'s own `max_temp` for the extruder, and bed 110C, a deliberate margin below the
  config's 130C bed `max_temp`. Refused if Klipper is not in the `ready` state.
- `pause_print`, `resume_print`, `cancel_print` - job control. `cancel_print` is irreversible.
- `tune_live` - adjust pressure advance (0..1), Z offset (-2..2 mm), flow percent (50..150),
  fan percent (0..100) on the running or next print. Ranges are enforced; each provided value
  becomes its own g-code line sent under one confirmation.
- `send_gcode` - send raw g-code or a Klipper macro, verbatim, no rewriting. The numeric
  ceilings above do not apply here; the preview shows exactly what will be sent, so read it. This
  is the general escape hatch behind the specific tools above; prefer those when they fit.
- `firmware_restart` - run `FIRMWARE_RESTART` to recover Klipper from a shutdown state. Unlike
  the other control tools, this one works even when Klipper is not ready (it is the fix for
  not-ready).
- `start_print` - start a print. Takes either a local g-code file on this machine (uploaded to
  the printer under its basename) or a filename already staged on the printer. A bare name that
  also exists as a local file in this server's working directory is treated as local and
  uploaded; the preview's `upload_needed` and `overwrites_existing` fields show which. Refused
  unless Klipper is ready and idle.

`emergency_stop` is the one exception: it acts immediately, with no preview and no `confirm`
argument, because a confirmation round-trip would defeat the point of an emergency stop. It
halts the printer at once (heaters and motors off); recover with `firmware_restart`.

### Memory

- `record_verdict` - attach a short human quality note ("warped", "clean", "layer shift at
  40%") to a finished print in the shared outcome store. Defaults to the most recently finished
  print.

## The capture service

`klipper-mcp-capture` is meant to run always-on (a systemd unit is in `deploy/`, currently
installed as `klipper-mcp-capture.service`). It holds a Moonraker websocket connection and, for
every print that finishes (completed, cancelled, or otherwise ended), records a row in the
shared SQLite store: job id, result, duration, filament grams, and whatever slicer settings
Moonraker's own g-code metadata carries. On every reconnect it also backfills from Moonraker's
REST history for anything finished while the service was down, so a restart or network blip
does not lose a job.

The unit in `deploy/` runs sandboxed: read-only view of the system and home directory except
the outcome store directory, private `/tmp`, no new privileges, no capabilities, and a
`@system-service` syscall filter. If you point `PRINT_OUTCOMES_DIR` somewhere else, add that
path to `ReadWritePaths=` too or the service will not be able to write the database.

The store lives at `PRINT_OUTCOMES_DIR/outcomes.db` (default
`~/projects/_shared/print-outcomes/outcomes.db`). `klipper-mcp` owns the schema; it is a plain
SQLite file, safe to read from outside this project.

Inspect the last 10 recorded prints:

```bash
sqlite3 ~/projects/_shared/print-outcomes/outcomes.db \
  'select gcode_filename,result,filament_g,human_verdict from prints order by id desc limit 10'
```

## Safety

- Every control tool but `emergency_stop` is two-phase: the first call previews, the second
  (with `confirm=true`) acts. This is enforced in the server, not left to the MCP client, because
  these sessions typically run without a permission prompt.
- `set_temperature` and `tune_live` enforce hard numeric ceilings taken from the printer's own
  config; out-of-range values are refused before anything is sent.
- Most control tools require Klipper to be in the `ready` state first; `firmware_restart` is the
  deliberate exception, since it exists to recover from not-ready.
- `emergency_stop` is immediate by design: no preview, no confirm, because a delay would defeat
  its purpose.
- This is a LAN-only tool talking to a LAN-only Moonraker instance. There is no remote access
  and no camera integration.

## Companion project

[orcaslicer-mcp](https://github.com/MaxEllis/orcaslicer-mcp) slices models with OrcaSlicer. Since
orcaslicer-mcp 0.1.10 the two servers close the loop through this project's outcome store:
`save_gcode` saves the sliced G-code and records the slice (model, geometry, full settings) under a
filename; `start_print` here uploads that same file and starts it; the capture service writes the
real result onto the same row when the job finishes; and `recall_prints` reads it back before the
next slice of the same model. `klipper-mcp` owns the SQLite schema; orcaslicer-mcp carries a
vendored copy of the store module.

## License

AGPL-3.0-only.
