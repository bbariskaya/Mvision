from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ServiceError(Exception):
    def __init__(
        self,
        message: str,
        public_message: str,
        error_code: str,
        status_code: int = 500,
        process_id: str | None = None,
    ):
        super().__init__(message)
        self.public_message = public_message
        self.error_code = error_code
        self.status_code = status_code
        self.process_id = process_id


class ValidationError(ServiceError):
    def __init__(
        self, message: str, error_code: str = "INVALID_INPUT", process_id: str | None = None
    ):
        super().__init__(message, message, error_code, 422, process_id)


class NotFoundError(ServiceError):
    def __init__(self, message: str, process_id: str | None = None):
        super().__init__(message, "Resource not found.", "NOT_FOUND", 404, process_id)


class StorageError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, "Temporary storage error.", "STORAGE_ERROR", 503)


class VectorStoreError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, "Temporary vector index error.", "VECTOR_STORE_ERROR", 503)


class ConflictError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, message, "CONFLICT", 409)


class InferenceError(ServiceError):
    def __init__(self, message: str, process_id: str | None = None):
        super().__init__(
            message,
            "Face processing is temporarily unavailable.",
            "INFERENCE_ERROR",
            503,
            process_id,
        )


class JobNotFoundError(ServiceError):
    def __init__(self, job_id: str):
        super().__init__(
            f"Video job {job_id} was not found",
            "Video job not found.",
            "JOB_NOT_FOUND",
            404,
        )


class VideoError(ServiceError):
    def __init__(
        self,
        message: str,
        error_code: str,
        status_code: int = 422,
        process_id: str | None = None,
    ):
        super().__init__(message, message, error_code, status_code, process_id)


class LiveCameraError(ServiceError):
    def __init__(self, message: str, error_code: str, status_code: int):
        super().__init__(message, message, error_code, status_code)


class LiveSessionError(ServiceError):
    def __init__(self, message: str, error_code: str, status_code: int):
        super().__init__(message, message, error_code, status_code)


class LiveConnectorError(ServiceError):
    def __init__(self, message: str, error_code: str, status_code: int):
        super().__init__(message, message, error_code, status_code)


def add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if not request.url.path.startswith("/api/v1/live/"):
            return await request_validation_exception_handler(request, exc)
        code = (
            "LIVE_CONNECTOR_SPEC_INVALID"
            if request.url.path.startswith("/api/v1/live/connectors")
            else "LIVE_SESSION_SPEC_INVALID"
        )
        return JSONResponse(
            status_code=422,
            content={
                "code": code,
                "message": "Invalid live request.",
                "processId": None,
            },
        )

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        if isinstance(exc, LiveCameraError):
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.error_code}},
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.error_code,
                "message": exc.public_message,
                "processId": exc.process_id,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "processId": None,
            },
        )
