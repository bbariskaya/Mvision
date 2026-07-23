import json

import httpx
import pytest

from app.infrastructure.media.mediamtx_client import (
    MediaMtxClient,
    MediaMtxError,
    ingress_config,
)


@pytest.mark.asyncio
async def test_add_pull_path_uses_exact_control_endpoint() -> None:
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = MediaMtxClient(
        "http://mediamtx:9997",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )

    await client.add_path("ingress/abc", {"source": "rtsp://upstream/live"})

    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v3/config/paths/add/ingress/abc"
    assert json.loads(requests[0].content) == {"source": "rtsp://upstream/live"}
    await client.aclose()


def test_ingress_config_preserves_exact_source_contracts() -> None:
    assert ingress_config("whipPush", None) == {"source": "publisher"}
    assert ingress_config("rtspPull", "rtsps://camera/live") == {
        "source": "rtsps://camera/live",
        "rtspTransport": "tcp",
    }
    assert ingress_config("whepPull", "wheps://camera/live") == {"source": "wheps://camera/live"}


@pytest.mark.asyncio
async def test_get_and_delete_return_none_for_missing_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    client = MediaMtxClient("http://mediamtx:9997", 1, transport=httpx.MockTransport(handler))

    assert await client.get_config_path("ingress/missing") is None
    assert await client.get_active_path("ingress/missing") is None
    await client.delete_path("ingress/missing")
    await client.aclose()


@pytest.mark.asyncio
async def test_client_errors_never_include_response_body_or_source_url() -> None:
    secret = "rtsp://user:password@camera/live"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"failed source={secret}", request=request)

    client = MediaMtxClient("http://mediamtx:9997", 1, transport=httpx.MockTransport(handler))

    with pytest.raises(MediaMtxError) as raised:
        await client.add_path("ingress/secret", {"source": secret})

    assert raised.value.code == "MEDIAMTX_HTTP_ERROR"
    assert raised.value.status == 500
    assert secret not in str(raised.value)
    assert "failed source" not in str(raised.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_non_json_success_is_rejected_without_body_disclosure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json-secret", request=request)

    client = MediaMtxClient("http://mediamtx:9997", 1, transport=httpx.MockTransport(handler))

    with pytest.raises(MediaMtxError, match="MEDIAMTX_INVALID_RESPONSE"):
        await client.get_config_path("ingress/invalid")

    await client.aclose()


@pytest.mark.asyncio
async def test_list_config_paths_reads_every_control_api_page() -> None:
    pages = {
        "0": {
            "itemCount": 2,
            "pageCount": 2,
            "items": [{"name": "ingress/one", "source": "publisher"}],
        },
        "1": {
            "itemCount": 2,
            "pageCount": 2,
            "items": [{"name": "ingress/two", "source": "publisher"}],
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/config/paths/list"
        assert request.url.params["itemsPerPage"] == "100"
        return httpx.Response(200, json=pages[request.url.params["page"]])

    client = MediaMtxClient("http://mediamtx:9997", 1, transport=httpx.MockTransport(handler))

    paths = await client.list_config_paths()

    assert [path["name"] for path in paths] == ["ingress/one", "ingress/two"]
    await client.aclose()
