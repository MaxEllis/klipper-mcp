import pytest
from klipper_mcp import client


@pytest.fixture(autouse=True)
def _forget_learned_urls():
    """The client remembers which Moonraker URL last answered, process-wide. Tests must not
    inherit that memory from each other."""
    client._LEARNED.clear()
    yield
    client._LEARNED.clear()
