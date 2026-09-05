from klipper_mcp.errors import error_from_status, BadRequest, NotFound, ServerError


def test_moonraker_error_envelope_message():
    e = error_from_status(400, {"error": {"code": 400, "message": "Unable to start print"}})
    assert isinstance(e, BadRequest)
    assert "Unable to start print" in str(e)


def test_404_and_500():
    assert isinstance(error_from_status(404, {}), NotFound)
    assert isinstance(error_from_status(503, {}), ServerError)
