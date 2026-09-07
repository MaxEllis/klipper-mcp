from klipper_mcp.config import load_config


def test_defaults(monkeypatch):
    for k in ("MOONRAKER_URL", "MOONRAKER_FALLBACK_URL", "MOONRAKER_TIMEOUT", "PRINTER_ID"):
        monkeypatch.delenv(k, raising=False)
    c = load_config()
    assert c.base_url == "http://klipper.local:7125"
    assert c.fallback_url == "http://192.168.1.128:7125"
    assert c.timeout == 15.0
    assert c.printer_id == "swx2"


def test_env_overrides_and_trailing_slash(monkeypatch):
    monkeypatch.setenv("MOONRAKER_URL", "http://x:7125/")
    monkeypatch.setenv("MOONRAKER_FALLBACK_URL", "")
    monkeypatch.setenv("MOONRAKER_TIMEOUT", "3")
    monkeypatch.setenv("PRINTER_ID", "voron")
    c = load_config()
    assert c.base_url == "http://x:7125"
    assert c.fallback_url is None
    assert c.timeout == 3.0
    assert c.printer_id == "voron"


def test_connect_timeout_default_is_short_and_overridable(monkeypatch):
    # mDNS resolution failures should cost seconds, not the full request timeout.
    monkeypatch.delenv("MOONRAKER_CONNECT_TIMEOUT", raising=False)
    assert load_config().connect_timeout == 3.0
    monkeypatch.setenv("MOONRAKER_CONNECT_TIMEOUT", "1.5")
    assert load_config().connect_timeout == 1.5
