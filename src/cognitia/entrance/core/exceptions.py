"""Custom exceptions for the application."""


class CognitiaException(Exception):
    """Base exception for all Cognitia errors."""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


# Authentication Exceptions
class InvalidCredentialsError(CognitiaException):
    """Invalid email or password."""
    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(message, status_code=401)


class EmailAlreadyExistsError(CognitiaException):
    """Email already registered."""
    def __init__(self, message: str = "Email already exists"):
        super().__init__(message, status_code=409)


class EmailNotVerifiedError(CognitiaException):
    """Email not verified."""
    def __init__(self, message: str = "Email not verified"):
        super().__init__(message, status_code=403)


class InvalidTokenError(CognitiaException):
    """Invalid or expired token."""
    def __init__(self, message: str = "Invalid token"):
        super().__init__(message, status_code=401)


class UnauthorizedError(CognitiaException):
    """User not authorized."""
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, status_code=403)


# Resource Exceptions
class ResourceNotFoundError(CognitiaException):
    """Resource not found."""
    def __init__(self, resource: str, id: str):
        super().__init__(f"{resource} with id {id} not found", status_code=404)


class ResourceAccessDeniedError(CognitiaException):
    """Access denied to resource."""
    def __init__(self, message: str = "Access denied"):
        super().__init__(message, status_code=403)


class VoicePermissionDeniedError(CognitiaException):
    """Voice model access denied."""
    def __init__(self, message: str = "Voice model access denied"):
        super().__init__(message, status_code=403)


# Subscription Exceptions
class SubscriptionRequiredError(CognitiaException):
    """Active subscription required."""
    def __init__(self, message: str = "Active subscription required"):
        super().__init__(message, status_code=402)


class UsageLimitExceededError(CognitiaException):
    """Usage limit exceeded."""
    def __init__(self, limit_type: str):
        super().__init__(f"{limit_type} limit exceeded", status_code=429)


# Validation Exceptions
class ValidationError(CognitiaException):
    """Validation error."""
    def __init__(self, message: str):
        super().__init__(message, status_code=400)


class InvalidInputError(CognitiaException):
    """Invalid input data."""
    def __init__(self, message: str):
        super().__init__(message, status_code=400)
