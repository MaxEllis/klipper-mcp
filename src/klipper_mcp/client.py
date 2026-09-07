"""Async Moonraker REST client. Mirrors orcaslicer-mcp's OrcaClient shape."""
from __future__ import annotations
import asyncio
from pathlib import Path
import httpx
from .config import Config
from .errors import NotReachable, error_from_status


# Process-wide memory of which URL last answered, keyed by the configured primary URL.
# Every tool call builds a fresh client, so without this each call would re-pay the mDNS
# failure (connect timeout) before reaching the fallback IP. Cleared when the remembered
# URL stops answering, so a printer that moves back to its mDNS name is re-learned.
_LEARNED: dict[str, str] = {}


class MoonrakerClient:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._base = _LEARNED.get(cfg.base_url, cfg.base_url)
        self._tried: set[str] = set()
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(cfg.timeout, connect=cfg.connect_timeout))

    async def __aenter__(self) -> "MoonrakerClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._http.aclose()

    @property
    def base_url(self) -> str:
        return self._base

    def _candidates(self) -> list[str]:
        return [u for u in (self._cfg.base_url, self._cfg.fallback_url) if u]

    def _next_base(self) -> str | None:
        """The next configured URL this client has not yet tried, or None when all are spent."""
        self._tried.add(self._base)
        for u in self._candidates():
            if u not in self._tried:
                return u
        return None

    async def _request(self, method: str, path: str, *, params=None, files=None, data=None):
        try:
            resp = await self._http.request(method, self._base + path, params=params, files=files, data=data)
        except httpx.TransportError as e:
            # mDNS can fail while the wired IP still answers (or the reverse): try each configured
            # URL once per client, remember the one that answers, forget it if nothing does.
            nxt = self._next_base()
            if nxt is None:
                _LEARNED.pop(self._cfg.base_url, None)
                raise NotReachable(f"Moonraker not reachable at {self._base}: {e}") from e
            self._base = nxt
            return await self._request(method, path, params=params, files=files, data=data)
        _LEARNED[self._cfg.base_url] = self._base
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            raise error_from_status(resp.status_code, body)
        return body.get("result") if isinstance(body, dict) else body

    # --- read ---
    async def server_info(self) -> dict:
        return await self._request("GET", "/server/info")

    async def printer_info(self) -> dict:
        return await self._request("GET", "/printer/info")

    async def objects_query(self, objects: list[str]) -> dict:
        # Moonraker takes each object as a bare query key: ?extruder&heater_bed
        # objects must be single bare tokens (e.g. "extruder", "heater_bed") -- no
        # URL-encoding is applied here, so a name needing escaping would break the query.
        params = "&".join(objects)
        res = await self._request("GET", f"/printer/objects/query?{params}")
        return (res or {}).get("status", {})

    async def history_list(self, limit: int = 20, since: float | None = None) -> list[dict]:
        params = {"limit": limit, "order": "desc"}
        if since is not None:
            params["since"] = since
        res = await self._request("GET", "/server/history/list", params=params)
        return (res or {}).get("jobs", [])

    async def files_list(self, root: str = "gcodes") -> list[dict]:
        return await self._request("GET", "/server/files/list", params={"root": root}) or []

    # --- write ---
    async def upload_gcode(self, local_path: str, filename: str) -> dict:
        # httpx streams a file object synchronously while encoding the multipart body, which
        # would block the event loop for a large gcode; read it on a worker thread instead.
        content = await asyncio.to_thread(Path(local_path).read_bytes)
        return await self._request("POST", "/server/files/upload",
                                   files={"file": (filename, content, "application/octet-stream")},
                                   data={"root": "gcodes"})

    async def print_start(self, filename: str) -> str:
        return await self._request("POST", "/printer/print/start", params={"filename": filename})

    async def print_pause(self) -> str:
        return await self._request("POST", "/printer/print/pause")

    async def print_resume(self) -> str:
        return await self._request("POST", "/printer/print/resume")

    async def print_cancel(self) -> str:
        return await self._request("POST", "/printer/print/cancel")

    async def gcode_script(self, script: str) -> str:
        return await self._request("POST", "/printer/gcode/script", params={"script": script})

    async def emergency_stop(self) -> str:
        return await self._request("POST", "/printer/emergency_stop")

    async def firmware_restart(self) -> str:
        return await self._request("POST", "/printer/firmware_restart")
