from __future__ import annotations


class ApiError(Exception):
    pass


class NotReachable(ApiError):
    pass


class BadRequest(ApiError):
    pass


class NotFound(ApiError):
    pass


class ServerError(ApiError):
    pass


class PrinterNotReady(ApiError):
    """Klipper is not in the 'ready' state; control refused."""


class Refused(ApiError):
    """A control request was refused by our own bounds (e.g. temperature ceiling)."""


def error_from_status(status: int, body: dict) -> ApiError:
    # Moonraker wraps errors as {"error": {"code": N, "message": "..."}}.
    err = body.get("error") if isinstance(body, dict) else None
    msg = err.get("message") if isinstance(err, dict) else None
    msg = msg or f"HTTP {status}"
    if status == 400:
        return BadRequest(msg)
    if status == 404:
        return NotFound(msg)
    return ServerError(msg)
