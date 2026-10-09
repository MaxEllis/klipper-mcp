import pytest

from klipper_mcp.config import load_config
from klipper_mcp.errors import NotConfigured

ENV = ("MOONRAKER_URL", "MOONRAKER_FALLBACK_URL", "MOONRAKER_TIMEOUT", "PRINTER_ID")


def _clear(m):
    for k in ENV:
        m.delenv(k, raising=False)


def test_defaults(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("MOONRAKER_URL", "http://printer.local:7125")
    c = load_config()
    assert c.base_url == "http://printer.local:7125"
    assert c.fallback_url is None  # no built-in second address
    assert c.timeout == 15.0
    assert c.printer_id == "swx2"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_printer_address_is_required(monkeypatch, value):
    _clear(monkeypatch)
    if value is not None:
        monkeypatch.setenv("MOONRAKER_URL", value)
    with pytest.raises(NotConfigured, match="MOONRAKER_URL is not set"):
        load_config()


def test_env_overrides_and_trailing_slash(monkeypatch):
    monkeypatch.setenv("MOONRAKER_URL", "http://x:7125/")
    monkeypatch.setenv("MOONRAKER_FALLBACK_URL", "http://192.0.2.10:7125/")
    monkeypatch.setenv("MOONRAKER_TIMEOUT", "3")
    monkeypatch.setenv("PRINTER_ID", "voron")
    c = load_config()
    assert c.base_url == "http://x:7125"
    assert c.fallback_url == "http://192.0.2.10:7125"
    assert c.timeout == 3.0
    assert c.printer_id == "voron"
    monkeypatch.setenv("MOONRAKER_FALLBACK_URL", "")
    assert load_config().fallback_url is None


def test_connect_timeout_default_is_short_and_overridable(monkeypatch):
    # mDNS resolution failures should cost seconds, not the full request timeout.
    monkeypatch.setenv("MOONRAKER_URL", "http://printer.local:7125")
    monkeypatch.delenv("MOONRAKER_CONNECT_TIMEOUT", raising=False)
    assert load_config().connect_timeout == 3.0
    monkeypatch.setenv("MOONRAKER_CONNECT_TIMEOUT", "1.5")
    assert load_config().connect_timeout == 1.5
