class ObjectStorageError(Exception):
    def __init__(self, message: str, code: str = "OBJECT_STORAGE_ERROR"):
        super().__init__(message)
        self.code = code


class ObjectNotFoundError(ObjectStorageError):
    def __init__(self, message: str):
        super().__init__(message, code="OBJECT_NOT_FOUND")


class ObjectValidationError(ObjectStorageError):
    def __init__(self, message: str):
        super().__init__(message, code="OBJECT_VALIDATION_ERROR")
