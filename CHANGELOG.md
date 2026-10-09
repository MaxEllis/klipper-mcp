# Changelog

## [Unreleased]
### Changed
- `httpx` is now capped below 1.0. Its 1.0 pre-releases have no `AsyncClient`, so an install that resolved one (for example with pre-releases allowed) failed on the first printer call; the cap keeps a future 1.0 release from doing the same to fresh installs.
- `src/klipper_mcp/outcomes.py` is re-copied from orcaslicer-mcp, which now owns the outcome-store schema. Schema v2 adds the `failure_reason`, `est_time_s` and `est_filament_g` columns; they are added on the first write, and older readers keep working.
- The default store location is `PRINT_OUTCOMES_DIR`, else `~/projects/_shared/print-outcomes` if that folder already exists, else `~/.orcaslicer-mcp/outcomes`. The unit in `deploy/` sets `PRINT_OUTCOMES_DIR` explicitly.
- A finished job only joins a slice that was saved no later than the job started, with a 120 second allowance for clock differences between the machines.
- The store module's default `printer_id` is `unknown` when a caller passes none. The recorder always passes its configured `PRINTER_ID`.
- Requires the mcp SDK 2.x (`mcp>=2.2,<3`): `FastMCP` became `MCPServer`. The server now reports its own package version to clients.
- The Moonraker client remembers which URL (mDNS name or fallback IP) last answered, process-wide, so every tool call no longer re-pays a dead mDNS lookup; the memory is dropped if that URL stops answering and both are retried.
- Separate connect timeout (`MOONRAKER_CONNECT_TIMEOUT`, default 3s) so failover to the IP happens in seconds.
- `start_print` reads the gcode file on a worker thread instead of blocking the event loop while httpx encodes the upload.
- The capture systemd unit is sandboxed (ProtectSystem=strict, ProtectHome=read-only with the store directory writable, NoNewPrivileges, empty capability set, `@system-service` syscall filter).
- `MOONRAKER_URL` is required. There is no built-in printer address and no default `MOONRAKER_FALLBACK_URL`. Without it every tool returns an error that names the variable, and the capture service logs it and exits. The unit in `deploy/` is now a template with placeholders and no address: put your user, paths and printer address in a drop-in (see the README).
- `PRINTER_ID` defaults to the host name in `MOONRAKER_URL`, the same rule orcaslicer-mcp uses, instead of a fixed tag. Set it explicitly to keep the tag an existing store already uses. The re-copied store module gives a new store's `printer_id` column the default `unknown`.
### Added
- Read tools: get_printer_status, get_printer_info, list_print_history, list_gcode_files.
- Two-phase gated control: set_temperature, pause/resume/cancel_print, tune_live, send_gcode, firmware_restart; emergency_stop acts immediately.
- start_print uploads a local gcode to the printer and starts it, after confirmation.
- klipper-mcp-capture service records every finished print into the shared outcome store and backfills from history on reconnect.
- record_verdict attaches a human quality note to a finished print.
