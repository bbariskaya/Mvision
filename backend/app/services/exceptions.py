from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ServiceError(Exception):
    def __init__(self, message: str, public_message: str, error_code: str):
        super().__init__(message)
        self.public_message = public_message
        self.error_code = error_code


class ValidationError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, "Invalid input.", "INVALID_INPUT")


class NotFoundError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, "Resource not found.", "NOT_FOUND")


class StorageError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, "Temporary storage error.", "STORAGE_ERROR")


class VectorStoreError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, "Temporary vector index error.", "VECTOR_STORE_ERROR")


class ConflictError(ServiceError):
    def __init__(self, message: str):
        super().__init__(message, "Resource conflict.", "CONFLICT")


def add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": exc.error_code,
                "message": exc.public_message,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
            },
        )
