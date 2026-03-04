from typing import Any
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


class ApiError(Exception):
    def __init__(self, error_code: str, message: str, status_code: int, details: Any | None = None):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details


def error_payload(error_code: str, message: str, details: Any | None = None) -> dict:
    payload = {"error_code": error_code, "message": message}
    if details is not None:
        payload["details"] = details
    return payload


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_payload(exc.error_code, exc.message, exc.details))


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    field_errors = []
    for e in exc.errors():
        field_errors.append(
            {"loc": e.get("loc", []), "msg": e.get("msg", ""), "type": e.get("type", "")}
        )
    details = {"field_errors": field_errors}
    return JSONResponse(status_code=400, content=error_payload("VALIDATION_ERROR", "Validation error", details))