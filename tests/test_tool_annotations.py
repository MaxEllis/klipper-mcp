import anyio
import klipper_mcp.server as srv


def test_annotation_table_matches_registered_tools_exactly():
    assert set(srv.mcp._tool_manager._tools) == set(srv._TOOL_ANNOTATIONS)


def test_every_tool_has_title_and_hints():
    for name, tool in srv.mcp._tool_manager._tools.items():
        ann = tool.annotations
        assert ann is not None and ann.title, name
        if ann.read_only_hint:
            assert ann.destructive_hint is None, name
        else:
            assert ann.destructive_hint in (True, False), name


def test_read_tools_are_read_only():
    tools = {t.name: t for t in anyio.run(srv.mcp.list_tools)}
    for n in ("get_printer_status", "get_printer_info", "list_print_history", "list_gcode_files"):
        assert tools[n].annotations.read_only_hint is True, n
