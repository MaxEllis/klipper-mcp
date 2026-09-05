import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    base_url: str
    fallback_url: str | None
    timeout: float
    printer_id: str


def load_config() -> Config:
    base_url = os.environ.get("MOONRAKER_URL", "http://klipper.local:7125").rstrip("/")
    fb = os.environ.get("MOONRAKER_FALLBACK_URL", "http://192.168.1.128:7125").strip().rstrip("/")
    timeout = float(os.environ.get("MOONRAKER_TIMEOUT", "15"))
    printer_id = os.environ.get("PRINTER_ID", "swx2").strip() or "swx2"
    return Config(base_url=base_url, fallback_url=fb or None, timeout=timeout, printer_id=printer_id)
