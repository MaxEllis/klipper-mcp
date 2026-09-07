# Changelog

## [Unreleased]
### Changed
- The Moonraker client remembers which URL (mDNS name or fallback IP) last answered, process-wide, so every tool call no longer re-pays a dead mDNS lookup; the memory is dropped if that URL stops answering and both are retried.
- Separate connect timeout (`MOONRAKER_CONNECT_TIMEOUT`, default 3s) so failover to the IP happens in seconds.
- `start_print` reads the gcode file on a worker thread instead of blocking the event loop while httpx encodes the upload.
- The capture systemd unit is sandboxed (ProtectSystem=strict, ProtectHome=read-only with the store directory writable, NoNewPrivileges, empty capability set, `@system-service` syscall filter).
### Added
- Read tools: get_printer_status, get_printer_info, list_print_history, list_gcode_files.
- Two-phase gated control: set_temperature, pause/resume/cancel_print, tune_live, send_gcode, firmware_restart; emergency_stop acts immediately.
- start_print uploads a local gcode to the printer and starts it, after confirmation.
- klipper-mcp-capture service records every finished print into the shared outcome store and backfills from history on reconnect.
- record_verdict attaches a human quality note to a finished print.
