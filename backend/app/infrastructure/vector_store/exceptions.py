class VectorStoreError(Exception):
    def __init__(self, message: str, code: str = "VECTOR_STORE_ERROR"):
        super().__init__(message)
        self.code = code


class VectorValidationError(VectorStoreError):
    def __init__(self, message: str):
        super().__init__(message, code="VECTOR_VALIDATION_ERROR")
