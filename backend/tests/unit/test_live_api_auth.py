from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.presentation.auth import require_live_api_key


def _app() -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        _env_file=None,
        live_api_key=SecretStr("secret"),
    )

    @app.get("/protected", dependencies=[Depends(require_live_api_key)])
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_live_api_rejects_missing_or_wrong_key() -> None:
    client = TestClient(_app())

    missing = client.get("/protected")
    wrong = client.get("/protected", headers={"X-API-Key": "wrong"})
    accepted = client.get("/protected", headers={"X-API-Key": "secret"})

    assert missing.status_code == 401
    assert missing.json()["detail"] == {"code": "LIVE_API_KEY_INVALID"}
    assert wrong.status_code == 401
    assert accepted.json() == {"ok": True}


def test_live_api_key_is_registered_as_openapi_security_scheme() -> None:
    schema = _app().openapi()

    assert schema["components"]["securitySchemes"]["LiveApiKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    assert schema["paths"]["/protected"]["get"]["security"] == [
        {"LiveApiKey": []}
    ]
