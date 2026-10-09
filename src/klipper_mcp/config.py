import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import NotConfigured


@dataclass(frozen=True)
class Config:
    base_url: str
    fallback_url: str | None
    timeout: float
    printer_id: str
    connect_timeout: float = 3.0


def load_config() -> Config:
    # No built-in printer address: a guessed default only turns "not configured" into a
    # confusing "not reachable".
    base_url = os.environ.get("MOONRAKER_URL", "").strip().rstrip("/")
    if not base_url:
        raise NotConfigured("MOONRAKER_URL is not set. Set it to your printer's Moonraker address, "
                            "for example http://printer.local:7125")
    fb = os.environ.get("MOONRAKER_FALLBACK_URL", "").strip().rstrip("/")
    timeout = float(os.environ.get("MOONRAKER_TIMEOUT", "15"))
    # Connect phase only: an mDNS name that no longer resolves should fail in seconds,
    # not sit out the full request timeout before the fallback IP is tried.
    connect_timeout = float(os.environ.get("MOONRAKER_CONNECT_TIMEOUT", "3"))
    # Same rule as orcaslicer-mcp: an explicit PRINTER_ID, else the printer's host name.
    printer_id = os.environ.get("PRINTER_ID", "").strip() or urlsplit(base_url).hostname or "unknown"
    return Config(base_url=base_url, fallback_url=fb or None, timeout=timeout, connect_timeout=connect_timeout,
                  printer_id=printer_id)
