import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    base_url: str
    fallback_url: str | None
    timeout: float
    printer_id: str
    connect_timeout: float = 3.0


def load_config() -> Config:
    base_url = os.environ.get("MOONRAKER_URL", "http://klipper.local:7125").rstrip("/")
    fb = os.environ.get("MOONRAKER_FALLBACK_URL", "http://192.168.1.128:7125").strip().rstrip("/")
    timeout = float(os.environ.get("MOONRAKER_TIMEOUT", "15"))
    # Connect phase only: an mDNS name that no longer resolves should fail in seconds,
    # not sit out the full request timeout before the fallback IP is tried.
    connect_timeout = float(os.environ.get("MOONRAKER_CONNECT_TIMEOUT", "3"))
    printer_id = os.environ.get("PRINTER_ID", "swx2").strip() or "swx2"
    return Config(base_url=base_url, fallback_url=fb or None, timeout=timeout, connect_timeout=connect_timeout,
                  printer_id=printer_id)
