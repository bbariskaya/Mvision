import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

_LIST_PAGE_SIZE = 100
_MAX_LIST_PAGES = 10_000


class MediaMtxError(RuntimeError):
    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class MediaMtxPathSpec:
    name: str
    config: dict[str, Any]


@dataclass(frozen=True)
class MediaMtxPathState:
    name: str
    online: bool


def ingress_config(source_type: str, source_url: str | None) -> dict[str, Any]:
    if source_type == "whipPush":
        return {"source": "publisher"}
    if source_type == "rtspPull":
        if source_url is None or not source_url.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("LIVE_SOURCE_CREDENTIAL_INVALID")
        return {"source": source_url, "rtspTransport": "tcp"}
    if source_type == "whepPull":
        if source_url is None or not source_url.lower().startswith(("whep://", "wheps://")):
            raise ValueError("LIVE_SOURCE_CREDENTIAL_INVALID")
        return {"source": source_url}
    raise ValueError("LIVE_SOURCE_TYPE_UNSUPPORTED")


class MediaMtxClient:
    def __init__(
        self,
        control_url: str,
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
        self._client = httpx.AsyncClient(
            base_url=control_url.rstrip("/") + "/",
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_config_path(self, name: str) -> dict[str, Any] | None:
        return await self._get_optional(f"v3/config/paths/get/{self._path(name)}")

    async def add_path(self, name: str, config: dict[str, Any]) -> None:
        await self._write("POST", f"v3/config/paths/add/{self._path(name)}", config)

    async def replace_path(self, name: str, config: dict[str, Any]) -> None:
        await self._write("POST", f"v3/config/paths/replace/{self._path(name)}", config)

    async def delete_path(self, name: str) -> None:
        await self._write(
            "DELETE", f"v3/config/paths/delete/{self._path(name)}", None, allow_404=True
        )

    async def get_active_path(self, name: str) -> dict[str, Any] | None:
        return await self._get_optional(f"v3/paths/get/{self._path(name)}")

    async def list_config_paths(self) -> list[dict[str, Any]]:
        paths: list[dict[str, Any]] = []
        page = 0
        while True:
            payload = await self._get_required(
                "v3/config/paths/list",
                params={"itemsPerPage": _LIST_PAGE_SIZE, "page": page},
            )
            items = payload.get("items")
            page_count = payload.get("pageCount", 1)
            if (
                not isinstance(items, list)
                or not all(isinstance(item, dict) for item in items)
                or type(page_count) is not int
                or page_count < 0
                or page_count > _MAX_LIST_PAGES
            ):
                raise MediaMtxError("MEDIAMTX_INVALID_RESPONSE")
            paths.extend(items)
            page += 1
            if page >= page_count:
                return paths

    async def _get_optional(self, path: str) -> dict[str, Any] | None:
        response = await self._request("GET", path)
        if response.status_code == 404:
            return None
        self._raise_status(response)
        return self._json_object(response)

    async def _get_required(
        self, path: str, *, params: dict[str, int] | None = None
    ) -> dict[str, Any]:
        response = await self._request("GET", path, params=params)
        self._raise_status(response)
        return self._json_object(response)

    async def _write(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        *,
        allow_404: bool = False,
    ) -> None:
        response = await self._request(method, path, json=payload)
        if allow_404 and response.status_code == 404:
            return
        self._raise_status(response)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, int] | None = None,
    ) -> httpx.Response:
        try:
            return await self._client.request(method, path, json=json, params=params)
        except httpx.TimeoutException as exc:
            raise MediaMtxError("MEDIAMTX_TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise MediaMtxError("MEDIAMTX_UNAVAILABLE") from exc

    @staticmethod
    def _raise_status(response: httpx.Response) -> None:
        if not response.is_success:
            raise MediaMtxError("MEDIAMTX_HTTP_ERROR", response.status_code)

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MediaMtxError("MEDIAMTX_INVALID_RESPONSE") from exc
        if not isinstance(payload, dict):
            raise MediaMtxError("MEDIAMTX_INVALID_RESPONSE")
        return payload

    @staticmethod
    def _path(name: str) -> str:
        parts = name.split("/")
        if not parts or any(not part or part in {".", ".."} for part in parts):
            raise ValueError("INVALID_MEDIAMTX_PATH")
        return "/".join(quote(part, safe="") for part in parts)
