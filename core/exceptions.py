from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler
from django.http import Http404
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError


class ContractAPIException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "VALIDATION_ERROR"
    default_detail = "Bad request"

    def __init__(self, message=None, code=None, status_code=None, details=None):
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        else:
            self.code = self.default_code
        self.message = str(message) if message is not None else self.default_detail
        self.details = details if details is not None else []
        super().__init__(self.message, code=self.code)


class ValidationError(ContractAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "VALIDATION_ERROR"


class NotFound(ContractAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "NOT_FOUND"
    default_detail = "Resource not found"


class DuplicateError(ContractAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "DUPLICATE"
    default_detail = "Resource already exists"


class InsufficientStockError(ContractAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "INSUFFICIENT_STOCK"
    default_detail = "Insufficient stock"


class InvalidTransitionError(ContractAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "INVALID_TRANSITION"
    default_detail = "Invalid status transition"


class OrderLockedError(ContractAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "ORDER_LOCKED"
    default_detail = "Order is locked and cannot be edited"


class IdempotencyConflictError(ContractAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "IDEMPOTENCY_CONFLICT"
    default_detail = "Idempotency key reused with different request parameters"


def contract_exception_handler(exc, context):
    """Formats all exceptions to match API_CONTRACT.md section 3:
    {"error": {"code": "...", "message": "...", "details": []}}
    """
    from rest_framework.response import Response

    if isinstance(exc, ContractAPIException):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=exc.status_code,
        )

    if isinstance(exc, Http404):
        return Response(
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(exc) or "Resource not found",
                    "details": [],
                }
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(exc.message if hasattr(exc, "message") else exc),
                    "details": exc.messages if hasattr(exc, "messages") else [str(exc)],
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, IntegrityError):
        return Response(
            {
                "error": {
                    "code": "DUPLICATE",
                    "message": "Resource already exists",
                    "details": [str(exc)],
                }
            },
            status=status.HTTP_409_CONFLICT,
        )

    # Let standard DRF exception handler process first
    response = exception_handler(exc, context)

    if response is not None:
        error_code = "VALIDATION_ERROR"
        if response.status_code == status.HTTP_404_NOT_FOUND:
            error_code = "NOT_FOUND"
        elif response.status_code == status.HTTP_409_CONFLICT:
            error_code = "DUPLICATE"

        details = []
        message = "Validation error"

        if isinstance(response.data, dict):
            if "detail" in response.data:
                message = str(response.data["detail"])
            else:
                formatted_details = []
                for field, errs in response.data.items():
                    if isinstance(errs, list):
                        for e in errs:
                            formatted_details.append(f"{field}: {e}")
                    else:
                        formatted_details.append(f"{field}: {errs}")
                details = formatted_details
                if formatted_details:
                    message = formatted_details[0]
        elif isinstance(response.data, list):
            details = [str(x) for x in response.data]
            if details:
                message = details[0]

        response.data = {
            "error": {
                "code": error_code,
                "message": message,
                "details": details,
            }
        }
        return response

    return None
