# Changelog

## [Unreleased]
### Added
- Read tools: get_printer_status, get_printer_info, list_print_history, list_gcode_files.
- Two-phase gated control: set_temperature, pause/resume/cancel_print, tune_live, send_gcode, firmware_restart; emergency_stop acts immediately.
- start_print uploads a local gcode to the printer and starts it, after confirmation.
- klipper-mcp-capture service records every finished print into the shared outcome store and backfills from history on reconnect.
- record_verdict attaches a human quality note to a finished print.
